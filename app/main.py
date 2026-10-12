"""FastAPI application entry point.

Wires the product router under ``/api/v1`` and installs error handlers that
never leak SQL, connection URLs, stack traces or credentials:

* validation errors become the standard 422 array, sanitised so that
  ``NaN``/``Infinity`` or exception objects cannot break JSON serialisation;
* database-unavailable errors (operational/interface/pool-timeout) become a
  short 503;
* anything unexpected becomes a short 500.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.routers import products as products_router
from app.schemas import sanitize_validation_errors

DATABASE_UNAVAILABLE_DETAIL = "Database unavailable"
INTERNAL_ERROR_DETAIL = "Internal server error"

app = FastAPI(
    title="GainMiles Product API",
    version="0.1.0",
    description=(
        "Product JSON REST API: create, read, list, replace and delete. "
        "`sizes` and `colors` accept a JSON array or a delimited string and "
        "are always returned as a sorted array."
    ),
)

app.include_router(products_router.router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return the standard 422 detail array, safe to JSON-serialise."""
    return JSONResponse(
        status_code=422,
        content={"detail": sanitize_validation_errors(exc.errors())},
    )


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a credential-free 503 when the database cannot be reached."""
    return JSONResponse(
        status_code=503, content={"detail": DATABASE_UNAVAILABLE_DETAIL}
    )


for _database_error in (OperationalError, InterfaceError, SQLAlchemyTimeoutError):
    app.add_exception_handler(_database_error, database_unavailable_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a short 500 without SQL, stack traces or connection details."""
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})
