"""initial schema: six product tables

Creates the categories/products/sizes/colors dictionaries and the two
many-to-many association tables with their constraints. Constraint names are
written out explicitly so that Alembic autogenerate stays stable.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-12

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )

    op.create_table(
        "sizes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_sizes"),
        sa.UniqueConstraint("code", name="uq_sizes_code"),
    )

    op.create_table(
        "colors",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_colors"),
        sa.UniqueConstraint("name", name="uq_colors_name"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("inventory", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price <= 99999999.99",
            name="unit_price_range",
        ),
        sa.CheckConstraint("inventory >= 0", name="inventory_nonneg"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_products_category_id_categories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("code", name="uq_products_code"),
    )

    op.create_table(
        "product_sizes",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("size_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_sizes_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["size_id"],
            ["sizes.id"],
            name="fk_product_sizes_size_id_sizes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("product_id", "size_id", name="pk_product_sizes"),
    )

    op.create_table(
        "product_colors",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_colors_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["color_id"],
            ["colors.id"],
            name="fk_product_colors_color_id_colors",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("product_id", "color_id", name="pk_product_colors"),
    )


def downgrade() -> None:
    op.drop_table("product_colors")
    op.drop_table("product_sizes")
    op.drop_table("products")
    op.drop_table("colors")
    op.drop_table("sizes")
    op.drop_table("categories")
