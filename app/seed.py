"""Load the four sample products: ``python -m app.seed``.

The whole batch runs in one transaction. A product code that already exists is
skipped, never overwritten, so running the command again (or after editing a
product) leaves the data as it is. Nothing else is created or deleted.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Product
from app.schemas import ProductCreate
from app.services.products import insert_product

SEED_PRODUCTS: tuple[dict[str, object], ...] = (
    {
        "name": "Star",
        "code": "A-001",
        "category": "cloth",
        "sizes": ["S", "M"],
        "unit_price": "200.00",
        "inventory": 20,
        "colors": ["Red", "Blue"],
    },
    {
        "name": "Moon",
        "code": "A-002",
        "category": "cloth",
        "sizes": ["M", "L"],
        "unit_price": "300.00",
        "inventory": 10,
        "colors": ["Red", "White"],
    },
    {
        "name": "Eagle",
        "code": "B-001",
        "category": "pants",
        "sizes": ["M", "L"],
        "unit_price": "100.00",
        "inventory": 23,
        "colors": ["Green"],
    },
    {
        "name": "Bird",
        "code": "B-002",
        "category": "pants",
        "sizes": ["S", "M", "L"],
        "unit_price": "50.00",
        "inventory": 12,
        "colors": ["Black"],
    },
)


def seed(session: Session, entries: Sequence[dict[str, object]] = SEED_PRODUCTS) -> tuple[int, int]:
    """Insert the missing sample products in one transaction.

    Returns ``(created, skipped)``. Existing codes are skipped without being
    modified; the batch commits only when all inserts succeed.
    """
    created = 0
    skipped = 0
    try:
        for entry in entries:
            data = ProductCreate.model_validate(entry)
            exists = session.scalar(select(Product.id).where(Product.code == data.code))
            if exists is not None:
                skipped += 1
                continue
            insert_product(session, data)
            created += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return created, skipped


def main() -> int:
    """Command-line entry point; prints counts only, never credentials."""
    from app.db import get_session_factory

    try:
        factory = get_session_factory()
        with factory() as session:
            created, skipped = seed(session)
    except RuntimeError as error:
        # The type only: a RuntimeError message could later carry a target or
        # credential, and the contract is that a failure prints no detail.
        print(f"seed failed: {type(error).__name__}")
        return 1
    except SQLAlchemyError as error:
        # The exception name only: a driver message can echo the connection target.
        print(f"seed failed: {type(error).__name__}")
        return 1
    print(f"seeded {created} product(s), skipped {skipped} existing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
