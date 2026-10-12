"""Product services: the transaction boundary for every write.

Attribute dictionaries (categories/sizes/colors) are looked up or created
inside the same transaction as the product, using PostgreSQL ``INSERT ... ON
CONFLICT DO NOTHING`` followed by a lookup. Values are handled in sorted order
so that concurrent writers take locks in a stable sequence. Updates lock the
product row with ``SELECT ... FOR UPDATE`` before replacing the size/color
collections, so two concurrent replacements cannot interleave into a mixed set.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Category, Color, Product, Size, product_colors, product_sizes
from app.schemas import ProductCreate, ProductRead

CODE_CONSTRAINT = "uq_products_code"


class DuplicateCode(Exception):
    """Raised when a product code collides with ``uq_products_code``."""


def is_code_conflict(error: IntegrityError) -> bool:
    """True only when the integrity error is the products.code unique index."""
    original = getattr(error, "orig", None)
    diag = getattr(original, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    if constraint:
        return constraint == CODE_CONSTRAINT
    return CODE_CONSTRAINT in str(original or "")


def _flush_or_code_conflict(session: Session) -> None:
    """Flush pending changes; translate only the code unique violation."""
    try:
        session.flush()
    except IntegrityError as error:
        if is_code_conflict(error):
            raise DuplicateCode() from None
        raise


# --- attribute dictionaries -------------------------------------------------


def _resolve_attributes(
    session: Session, model: type[Category] | type[Size] | type[Color], column: str, values: Iterable[str]
) -> list[Category | Size | Color]:
    """Return the dictionary rows for ``values``, creating missing ones.

    ``values`` is de-duplicated and sorted first. Each value is upserted with
    ``ON CONFLICT DO NOTHING`` (safe against a concurrent creator) and then all
    rows are read back in one query, so a normal shared-attribute race never
    looks like a product-code conflict.
    """
    ordered = sorted(set(values))
    attribute = getattr(model, column)
    for value in ordered:
        session.execute(
            pg_insert(model)
            .values(**{column: value})
            .on_conflict_do_nothing(index_elements=[column])
        )
    rows = session.execute(select(model).where(attribute.in_(ordered))).scalars().all()
    by_label = {getattr(row, column): row for row in rows}
    missing = [value for value in ordered if value not in by_label]
    if missing:  # pragma: no cover - only if a concurrent delete removed a row
        raise RuntimeError("attribute row missing after upsert")
    return [by_label[value] for value in ordered]


def _resolve_category(session: Session, name: str) -> Category:
    return _resolve_attributes(session, Category, "name", [name])[0]  # type: ignore[return-value]


# --- reads ------------------------------------------------------------------


def _with_attributes(statement):
    return statement.options(
        selectinload(Product.category),
        selectinload(Product.sizes),
        selectinload(Product.colors),
    )


def get_product(session: Session, product_id: int) -> Product | None:
    """Return one product with its attributes loaded, or ``None``."""
    statement = _with_attributes(select(Product).where(Product.id == product_id))
    return session.execute(statement).scalar_one_or_none()


def list_products(session: Session, limit: int, offset: int) -> tuple[list[Product], int]:
    """Return one page (id ascending) plus the total count before paging.

    No many-to-many join is used, so a product with several sizes/colors can
    never appear twice or inflate ``total``.
    """
    total = int(session.scalar(select(func.count(Product.id))) or 0)
    statement = (
        _with_attributes(select(Product))
        .order_by(Product.id)
        .limit(limit)
        .offset(offset)
    )
    products = list(session.execute(statement).scalars().all())
    return products, total


def to_read(product: Product) -> ProductRead:
    """Map ORM entities to the explicit response model.

    The category name and the size/color labels are read from the related
    objects and sorted here (case-sensitive ascending), rather than relying on
    ``from_attributes`` to turn an entity into text.
    """
    return ProductRead(
        id=product.id,
        name=product.name,
        code=product.code,
        category=product.category.name,
        sizes=sorted(size.code for size in product.sizes),
        unit_price=product.unit_price,
        inventory=product.inventory,
        colors=sorted(color.name for color in product.colors),
    )


# --- writes -----------------------------------------------------------------


def insert_product(session: Session, data: ProductCreate) -> Product:
    """Insert a product and its mappings *without* committing.

    Shared by :func:`create_product` and the seed command so a seed batch stays
    one transaction. Callers own the commit/rollback.
    """
    category = _resolve_category(session, data.category)
    sizes = _resolve_attributes(session, Size, "code", data.sizes)
    colors = _resolve_attributes(session, Color, "name", data.colors)

    product = Product(
        name=data.name,
        code=data.code,
        category=category,
        unit_price=data.unit_price,
        inventory=data.inventory,
    )
    product.sizes = sizes  # type: ignore[assignment]
    product.colors = colors  # type: ignore[assignment]
    session.add(product)
    _flush_or_code_conflict(session)
    return product


def create_product(session: Session, data: ProductCreate) -> Product:
    """Create a product in one transaction; raise :class:`DuplicateCode`."""
    try:
        product = insert_product(session, data)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return product


def update_product(session: Session, product_id: int, data: ProductCreate) -> Product | None:
    """Replace all seven fields of an existing product, or return ``None``.

    The product row is locked before its collections are replaced, so two
    concurrent replacements serialise instead of mixing. A code conflict or any
    other failure rolls the whole transaction back, including attributes that
    were created for this request only.
    """
    try:
        product = session.execute(
            select(Product).where(Product.id == product_id).with_for_update()
        ).scalar_one_or_none()
        if product is None:
            session.rollback()
            return None

        category = _resolve_category(session, data.category)
        sizes = _resolve_attributes(session, Size, "code", data.sizes)
        colors = _resolve_attributes(session, Color, "name", data.colors)

        product.name = data.name
        product.code = data.code
        product.category = category
        product.unit_price = data.unit_price
        product.inventory = data.inventory
        # Flush the scalar changes first: a code collision is then reported
        # before the collections are touched, and the collection assignment
        # below cannot trigger a query-invoked autoflush of a conflicting row.
        _flush_or_code_conflict(session)
        product.sizes = sizes  # type: ignore[assignment]
        product.colors = colors  # type: ignore[assignment]
        _flush_or_code_conflict(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return product


def delete_product(session: Session, product_id: int) -> bool:
    """Delete a product and its mappings; keep shared attributes.

    Returns ``False`` when the product does not exist.
    """
    try:
        product = session.get(Product, product_id, with_for_update=True)
        if product is None:
            session.rollback()
            return False
        session.execute(delete(product_sizes).where(product_sizes.c.product_id == product_id))
        session.execute(delete(product_colors).where(product_colors.c.product_id == product_id))
        session.delete(product)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return True


def read_many(session: Session, products: Sequence[Product]) -> list[ProductRead]:
    """Map a sequence of products to response models."""
    return [to_read(product) for product in products]
