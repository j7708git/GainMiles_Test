"""HTTP routes for the product resource (all under ``/api/v1``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ProductCreate, ProductPage, ProductRead
from app.services import products as product_service

router = APIRouter(tags=["products"])

CODE_CONFLICT_DETAIL = "Product code already exists"
NOT_FOUND_DETAIL = "Product not found"

ProductId = Path(
    gt=0,
    le=2147483647,
    description="Product id (a positive 32-bit integer)",
)

LimitQuery = Query(20, ge=1, le=100)
OffsetQuery = Query(0, ge=0, le=100000)


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> ProductRead:
    """Create a product from the seven writable fields."""
    try:
        product = product_service.create_product(session, payload)
    except product_service.DuplicateCode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=CODE_CONFLICT_DETAIL
        ) from None
    response.headers["Location"] = f"/api/v1/products/{product.id}"
    return product_service.to_read(product)


@router.get("/products", response_model=ProductPage)
def list_products(
    limit: int = LimitQuery,
    offset: int = OffsetQuery,
    session: Session = Depends(get_session),
) -> ProductPage:
    """List products by stable id ascending order."""
    products, total = product_service.list_products(session, limit=limit, offset=offset)
    return ProductPage(
        items=product_service.read_many(session, products),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductRead)
def read_product(
    product_id: int = ProductId,
    session: Session = Depends(get_session),
) -> ProductRead:
    """Read one product."""
    product = product_service.get_product(session, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return product_service.to_read(product)


@router.put("/products/{product_id}", response_model=ProductRead)
def replace_product(
    payload: ProductCreate,
    product_id: int = ProductId,
    session: Session = Depends(get_session),
) -> ProductRead:
    """Replace all seven writable fields; a missing id is not created."""
    try:
        product = product_service.update_product(session, product_id, payload)
    except product_service.DuplicateCode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=CODE_CONFLICT_DETAIL
        ) from None
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return product_service.to_read(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int = ProductId,
    session: Session = Depends(get_session),
) -> Response:
    """Delete a product and its mappings; shared attributes are kept."""
    deleted = product_service.delete_product(session, product_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
