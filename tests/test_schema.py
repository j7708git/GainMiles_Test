"""Schema and database-constraint tests.

These require a real PostgreSQL database and are run against the dedicated
``TEST_DATABASE_URL`` database (guarded in ``conftest.py``). When that database
is not reachable the tests report as skipped, never as passed.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.engine import Engine
import pytest

EXPECTED_TABLES = {
    "products",
    "categories",
    "sizes",
    "colors",
    "product_sizes",
    "product_colors",
}


def insert_category(conn, name: str = "cloth") -> int:
    return conn.execute(
        text("INSERT INTO categories (name) VALUES (:name) RETURNING id"),
        {"name": name},
    ).scalar_one()


def insert_product(
    conn,
    category_id: int,
    *,
    code: str = "A-001",
    name: str = "Star",
    unit_price: str = "200.00",
    inventory: int = 20,
) -> int:
    return conn.execute(
        text(
            "INSERT INTO products (name, code, category_id, unit_price, inventory) "
            "VALUES (:name, :code, :category_id, :unit_price, :inventory) "
            "RETURNING id"
        ),
        {
            "name": name,
            "code": code,
            "category_id": category_id,
            "unit_price": unit_price,
            "inventory": inventory,
        },
    ).scalar_one()


def insert_size(conn, code: str = "S") -> int:
    return conn.execute(
        text("INSERT INTO sizes (code) VALUES (:code) RETURNING id"), {"code": code}
    ).scalar_one()


def insert_color(conn, name: str = "Red") -> int:
    return conn.execute(
        text("INSERT INTO colors (name) VALUES (:name) RETURNING id"), {"name": name}
    ).scalar_one()


def link_size(conn, product_id: int, size_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO product_sizes (product_id, size_id) VALUES (:p, :s)"
        ),
        {"p": product_id, "s": size_id},
    )


def link_color(conn, product_id: int, color_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO product_colors (product_id, color_id) VALUES (:p, :c)"
        ),
        {"p": product_id, "c": color_id},
    )


def test_six_tables_exist(db_engine: Engine) -> None:
    names = set(inspect(db_engine).get_table_names())
    assert EXPECTED_TABLES <= names


def test_identity_assigns_distinct_ids(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        first = insert_product(conn, category_id, code="A-001")
        second = insert_product(conn, category_id, code="A-002")
    assert first > 0
    assert second != first


def test_product_code_is_unique(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        insert_product(conn, category_id, code="A-001")
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            insert_product(conn, category_id, code="A-001")


def test_product_name_cannot_be_blank(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, name="   ")


def test_product_code_cannot_be_blank(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, code="")


def test_product_name_cannot_be_null(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, name=None)  # type: ignore[arg-type]


def test_negative_price_rejected(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, unit_price="-0.01")


def test_negative_inventory_rejected(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, inventory=-1)


def test_price_above_maximum_rejected(db_engine: Engine) -> None:
    with pytest.raises(DBAPIError):
        with db_engine.begin() as conn:
            category_id = insert_category(conn)
            insert_product(conn, category_id, unit_price="100000000.00")


def test_zero_price_and_inventory_allowed(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        product_id = insert_product(conn, category_id, unit_price="0.00", inventory=0)
    assert product_id > 0


def test_maximum_price_allowed(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        product_id = insert_product(conn, category_id, unit_price="99999999.99")
    assert product_id > 0


def test_category_fk_requires_existing_category(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            insert_product(conn, category_id=999999)


def test_deleting_used_category_is_restricted(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        insert_product(conn, category_id)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM categories WHERE id = :id"), {"id": category_id}
            )


def test_deleting_product_cascades_mappings(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        product_id = insert_product(conn, category_id)
        size_id = insert_size(conn)
        color_id = insert_color(conn)
        link_size(conn, product_id, size_id)
        link_color(conn, product_id, color_id)

    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM products WHERE id = :id"), {"id": product_id})

    with db_engine.begin() as conn:
        sizes_left = conn.execute(
            text("SELECT count(*) FROM product_sizes")
        ).scalar_one()
        colors_left = conn.execute(
            text("SELECT count(*) FROM product_colors")
        ).scalar_one()
        # The shared attribute rows themselves are kept.
        size_rows = conn.execute(text("SELECT count(*) FROM sizes")).scalar_one()
    assert sizes_left == 0
    assert colors_left == 0
    assert size_rows == 1


def test_mapping_pair_must_be_unique(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        product_id = insert_product(conn, category_id)
        size_id = insert_size(conn)
        link_size(conn, product_id, size_id)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            link_size(conn, product_id, size_id)


def test_deleting_used_size_is_restricted(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        category_id = insert_category(conn)
        product_id = insert_product(conn, category_id)
        size_id = insert_size(conn)
        link_size(conn, product_id, size_id)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM sizes WHERE id = :id"), {"id": size_id})


def test_attribute_dictionaries_reject_blank_and_duplicates(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("INSERT INTO sizes (code) VALUES ('  ')"))
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            insert_category(conn, name="   ")
    with db_engine.begin() as conn:
        insert_color(conn, "Red")
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            insert_color(conn, "Red")
