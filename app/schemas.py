"""Request and response models for the product API.

A product has seven writable fields: ``name``, ``code``, ``category``,
``sizes``, ``unit_price``, ``inventory`` and ``colors``. ``id`` is assigned by
the server and never accepted in a request body (unknown fields are rejected).

``sizes``/``colors`` accept either a JSON array of labels or a single delimited
string (``、``, ``,`` or ``，``); both normalise to a sorted list of strings in
the response. ``unit_price`` accepts a JSON number or a decimal string and is
always returned as a two-decimal string. ``inventory`` is a strict JSON
integer.
"""

from __future__ import annotations

import functools
import math
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)

# --- sizes / colors normalisation -------------------------------------------

SEPARATORS = ("\u3001", ",", "\uff0c")

MAX_RAW_STRING_LENGTH = 4096
MAX_ITEMS = 50
MAX_SIZE_LENGTH = 32
MAX_COLOR_LENGTH = 64


def split_labels(value: Any, max_length: int) -> list[str]:
    """Normalise an array or delimited string into a trimmed label list.

    A string is length-checked *before* trimming; a list is treated as a list
    of complete labels and its elements must not contain a separator (no mixed
    formats). Empty or repeated labels are rejected, as is any label longer
    than ``max_length``. The input is never mutated.
    """
    if isinstance(value, str):
        if len(value) > MAX_RAW_STRING_LENGTH:
            raise ValueError("string is longer than 4096 characters")
        parts: list[str] = []
        buffer: list[str] = []
        for character in value:
            if character in SEPARATORS:
                parts.append("".join(buffer))
                buffer = []
            else:
                buffer.append(character)
        parts.append("".join(buffer))
        raw_items = parts
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("each item must be a string")
            if any(separator in item for separator in SEPARATORS):
                raise ValueError("items must not contain the separators")
            raw_items.append(item)
    else:
        raise ValueError("expected an array of strings or a delimited string")

    if not 1 <= len(raw_items) <= MAX_ITEMS:
        raise ValueError("must contain between 1 and 50 items")

    labels: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        label = raw.strip()
        if label == "":
            raise ValueError("items must not be empty")
        if len(label) > max_length:
            raise ValueError(f"each item must be at most {max_length} characters")
        if label in seen:
            raise ValueError("items must not repeat")
        seen.add(label)
        labels.append(label)
    return labels


normalize_sizes = functools.partial(split_labels, max_length=MAX_SIZE_LENGTH)
normalize_colors = functools.partial(split_labels, max_length=MAX_COLOR_LENGTH)

# --- unit_price --------------------------------------------------------------

MAX_PRICE = Decimal("99999999.99")
PRICE_QUANTUM = Decimal("0.01")


def coerce_price(value: Any) -> Decimal:
    """Accept a JSON number or decimal string; reject everything else.

    Booleans, ``null``, objects and arrays are rejected explicitly (Pydantic
    would otherwise treat some of them as numbers). Floats are converted via
    their shortest decimal representation so ``0.1 + 0.2`` style artefacts are
    not silently rounded into a "valid" price.
    """
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool):
        raise ValueError("unit_price must be a number or a decimal string")
    if isinstance(value, (dict, list, tuple, set)):
        raise ValueError("unit_price must be a number or a decimal string")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("unit_price must be a finite number")
        return Decimal(str(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise ValueError("unit_price must not be blank")
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ValueError("unit_price must be a decimal number") from None
    raise ValueError("unit_price must be a number or a decimal string")


def check_price(value: Decimal) -> Decimal:
    """Reject non-finite, negative, over-limit or over-precise prices.

    A value with more than two decimal places is accepted only when it can be
    represented exactly with two decimals (extra trailing zeros), e.g.
    ``200.000`` normalises to ``200.00`` while ``200.001`` is rejected.
    """
    if not value.is_finite():
        raise ValueError("unit_price must be a finite number")
    if value < 0:
        raise ValueError("unit_price must not be negative")
    if value > MAX_PRICE:
        raise ValueError("unit_price must not exceed 99999999.99")
    try:
        scaled = value.quantize(PRICE_QUANTUM)
    except InvalidOperation:
        raise ValueError("unit_price must have at most two decimal places") from None
    if scaled != value:
        raise ValueError("unit_price must have at most two decimal places")
    return scaled


Price = Annotated[
    Decimal,
    BeforeValidator(coerce_price),
    AfterValidator(check_price),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
]

TrimmedName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
TrimmedCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]
TrimmedCategory = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
Inventory = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class ProductCreate(BaseModel):
    """The seven writable fields shared by POST and PUT."""

    model_config = ConfigDict(extra="forbid")

    name: TrimmedName
    code: TrimmedCode
    category: TrimmedCategory
    sizes: list[str]
    unit_price: Price
    inventory: Inventory
    colors: list[str]

    @field_validator("sizes", mode="before", json_schema_input_type=str | list[str])
    @classmethod
    def _normalize_sizes(cls, value: Any) -> Any:
        return normalize_sizes(value)

    @field_validator("colors", mode="before", json_schema_input_type=str | list[str])
    @classmethod
    def _normalize_colors(cls, value: Any) -> Any:
        return normalize_colors(value)


class ProductRead(BaseModel):
    """The product representation returned by every successful endpoint."""

    id: int
    name: str
    code: str
    category: str
    sizes: list[str]
    unit_price: Price
    inventory: int
    colors: list[str]


class ProductPage(BaseModel):
    """One page of the product list; ``total`` ignores limit/offset."""

    items: list[ProductRead]
    total: int
    limit: int
    offset: int


# --- safe validation-error serialisation ------------------------------------


def json_safe(value: Any) -> Any:
    """Return a value that ``json.dumps`` can always serialise.

    Validation errors can carry ``NaN``/``Infinity`` floats and exception
    objects in ``input``/``ctx``. Serialising those with Starlette's
    ``JSONResponse`` (which passes ``allow_nan=False``) would turn a 422 into a
    500, so every leaf is normalised here first.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert FastAPI/Pydantic validation errors into JSON-safe dicts."""
    safe: list[dict[str, Any]] = []
    for error in errors:
        item: dict[str, Any] = {
            "type": json_safe(error.get("type")),
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": json_safe(error.get("msg")),
            "input": json_safe(error.get("input")),
        }
        if "ctx" in error:
            item["ctx"] = json_safe(error.get("ctx"))
        if "url" in error:
            item["url"] = json_safe(error.get("url"))
        safe.append(item)
    return safe
