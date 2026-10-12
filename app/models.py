"""SQLAlchemy models for the six-table product schema.

Tables: ``categories``, ``products``, ``sizes``, ``colors``,
``product_sizes`` and ``product_colors``. Product price and inventory live on
the product row; sizes and colors are multi-valued and linked through the two
association tables. The business rule "a product has at least one size and one
color" is enforced by the API transaction, not by a database trigger.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# --- Attribute dictionaries -------------------------------------------------


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")

    __table_args__ = (CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),)


class Size(Base):
    __tablename__ = "sizes"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    products: Mapped[list["Product"]] = relationship(
        secondary="product_sizes", back_populates="sizes"
    )

    __table_args__ = (CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),)


class Color(Base):
    __tablename__ = "colors"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    products: Mapped[list["Product"]] = relationship(
        secondary="product_colors", back_populates="colors"
    )

    __table_args__ = (CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),)


# --- Many-to-many association tables ----------------------------------------


product_sizes = Table(
    "product_sizes",
    Base.metadata,
    Column(
        "product_id",
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "size_id",
        ForeignKey("sizes.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    ),
)

product_colors = Table(
    "product_colors",
    Base.metadata,
    Column(
        "product_id",
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "color_id",
        ForeignKey("colors.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    ),
)


# --- Product ----------------------------------------------------------------


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    inventory: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped["Category"] = relationship(back_populates="products")
    sizes: Mapped[list["Size"]] = relationship(
        secondary=product_sizes, back_populates="products"
    )
    colors: Mapped[list["Color"]] = relationship(
        secondary=product_colors, back_populates="products"
    )

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        CheckConstraint(
            "unit_price >= 0 AND unit_price <= 99999999.99",
            name="unit_price_range",
        ),
        CheckConstraint("inventory >= 0", name="inventory_nonneg"),
    )
