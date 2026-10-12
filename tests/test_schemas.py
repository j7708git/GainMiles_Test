"""Request/response schema, boundary and OpenAPI tests — no database.

These exercise the Pydantic models directly plus the generated OpenAPI
document, so they run without PostgreSQL. HTTP-level error-body sanitisation
(NaN/Infinity → 422, never 500) is also checked here because body validation
fails before any database access.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db import get_session
from app.main import app
from app.schemas import (
    MAX_COLOR_LENGTH,
    MAX_ITEMS,
    MAX_PRICE,
    MAX_SIZE_LENGTH,
    ProductCreate,
    ProductRead,
    sanitize_validation_errors,
)

API = "/api/v1/products"


def valid(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "Star",
        "code": "A-001",
        "category": "cloth",
        "sizes": ["S", "M"],
        "unit_price": "200.00",
        "inventory": 20,
        "colors": ["Red", "Blue"],
    }
    data.update(overrides)
    return data


def parse(**overrides: object) -> ProductCreate:
    return ProductCreate.model_validate(valid(**overrides))


def reject(**overrides: object) -> ValidationError:
    with pytest.raises(ValidationError) as excinfo:
        parse(**overrides)
    return excinfo.value


@pytest.fixture(scope="module")
def openapi() -> dict:
    return app.openapi()


@pytest.fixture()
def client() -> TestClient:
    """A client whose session dependency is never used (validation only)."""

    def unused_session():
        yield None

    app.dependency_overrides[get_session] = unused_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- sizes / colors: input forms --------------------------------------------


def test_string_and_array_inputs_are_equivalent() -> None:
    from_string = parse(sizes="S、M", colors="Blue、Red")
    from_array = parse(sizes=["S", "M"], colors=["Blue", "Red"])
    assert from_string.sizes == from_array.sizes == ["S", "M"]
    assert from_string.colors == from_array.colors == ["Blue", "Red"]


@pytest.mark.parametrize("separator", ["\u3001", ",", "\uff0c"])
def test_each_separator_is_supported(separator: str) -> None:
    assert parse(colors=f"Blue{separator}Red").colors == ["Blue", "Red"]


def test_separators_can_be_mixed() -> None:
    # The schema preserves the given order; the API response sorts instead.
    assert parse(colors="Red、Blue，Green,Black").colors == [
        "Red",
        "Blue",
        "Green",
        "Black",
    ]


def test_single_string_is_one_label() -> None:
    assert parse(sizes="M", colors="Blue").colors == ["Blue"]
    # A space does not split; it stays inside the label.
    assert parse(colors="Blue Red").colors == ["Blue Red"]


def test_two_fields_can_use_different_input_types() -> None:
    product = parse(sizes="S、M", colors=["Red", "Blue"])
    assert product.sizes == ["S", "M"]
    assert product.colors == ["Red", "Blue"]


def test_labels_are_trimmed() -> None:
    product = parse(sizes="  S , M  ", colors=" Red ,  Blue ")
    assert product.sizes == ["S", "M"]
    assert product.colors == ["Red", "Blue"]


def test_case_is_significant() -> None:
    assert parse(colors=["Blue", "blue"]).colors == ["Blue", "blue"]


def test_array_element_with_separator_is_rejected() -> None:
    error = reject(colors=["Blue、Red"])
    assert "separators" in error.errors()[0]["msg"]


@pytest.mark.parametrize("value", [["S", ""], ["S", " "], "S,,M", "S,", ",S"])
def test_empty_items_are_rejected(value: object) -> None:
    error = reject(sizes=value)
    assert "empty" in error.errors()[0]["msg"]


@pytest.mark.parametrize("value", [["S", "S"], "S,S", "S、 S ", "M,M,M"])
def test_duplicate_items_are_rejected(value: object) -> None:
    error = reject(sizes=value)
    assert "repeat" in error.errors()[0]["msg"]


@pytest.mark.parametrize("value", ["", "  ", [], None, 123, ["S", 123], {"a": "S"}])
def test_bad_collection_types_are_rejected(value: object) -> None:
    reject(colors=value)


# --- sizes / colors: boundaries ---------------------------------------------


def test_raw_string_length_boundary() -> None:
    # 4096 raw characters is allowed past the raw-length gate, then the single
    # over-long label is rejected for its own length...
    item_error = reject(colors="R" * 4096).errors()[0]["msg"]
    assert "64 characters" in item_error
    # ...while 4097 is refused before item validation.
    raw_error = reject(colors="R" * 4097).errors()[0]["msg"]
    assert "4096" in raw_error


def test_item_count_boundary() -> None:
    fifty = [f"S{i}" for i in range(MAX_ITEMS)]
    assert len(parse(sizes=fifty).sizes) == MAX_ITEMS
    assert len(parse(sizes=",".join(fifty)).sizes) == MAX_ITEMS
    error = reject(sizes=[f"S{i}" for i in range(MAX_ITEMS + 1)])
    assert "50 items" in error.errors()[0]["msg"]
    error = reject(sizes=",".join(f"S{i}" for i in range(MAX_ITEMS + 1)))
    assert "50 items" in error.errors()[0]["msg"]


def test_item_length_limits() -> None:
    assert len(parse(sizes=["S" * MAX_SIZE_LENGTH]).sizes) == 1
    assert len(parse(colors=["C" * MAX_COLOR_LENGTH]).colors) == 1
    error = reject(sizes=["S" * (MAX_SIZE_LENGTH + 1)])
    assert "32 characters" in error.errors()[0]["msg"]
    error = reject(colors=["C" * (MAX_COLOR_LENGTH + 1)])
    assert "64 characters" in error.errors()[0]["msg"]


# --- text fields -------------------------------------------------------------


def test_text_fields_are_trimmed() -> None:
    product = parse(name="  Star  ", code="  A-001  ", category="  cloth  ")
    assert (product.name, product.code, product.category) == ("Star", "A-001", "cloth")


@pytest.mark.parametrize("field", ["name", "code", "category"])
@pytest.mark.parametrize("value", ["", "   ", None, 5, ["x"]])
def test_blank_or_wrong_text_values_are_rejected(field: str, value: object) -> None:
    reject(**{field: value})


@pytest.mark.parametrize(
    ("field", "length"),
    [("name", 128), ("code", 32), ("category", 64)],
)
def test_text_length_boundaries(field: str, length: int) -> None:
    assert len(getattr(parse(**{field: "x" * length}), field)) == length
    reject(**{field: "x" * (length + 1)})


# --- unit_price --------------------------------------------------------------


@pytest.mark.parametrize("value", [200, 200.0, "200", "200.00", "200.000", Decimal("200.00")])
def test_price_accepted_forms_normalise_to_two_decimals(value: object) -> None:
    product = parse(unit_price=value)
    assert product.unit_price == Decimal("200.00")
    assert product.model_dump(mode="json")["unit_price"] == "200.00"


@pytest.mark.parametrize("value", [0, 0.0, "0", "0.00", "99999999.99", 99999999.99])
def test_price_zero_and_max_are_accepted(value: object) -> None:
    assert parse(unit_price=value).unit_price >= Decimal("0")


@pytest.mark.parametrize("value", ["200.001", "0.005", 200.001])
def test_price_with_more_than_two_decimals_is_rejected(value: object) -> None:
    assert "two decimal places" in reject(unit_price=value).errors()[0]["msg"]


@pytest.mark.parametrize("value", ["-0.01", -1, "-1.00"])
def test_negative_price_is_rejected(value: object) -> None:
    assert "negative" in reject(unit_price=value).errors()[0]["msg"]


@pytest.mark.parametrize("value", ["100000000.00", 100000000, "99999999.995"])
def test_price_above_maximum_is_rejected(value: object) -> None:
    error = reject(unit_price=value)
    assert "99999999.99" in error.errors()[0]["msg"]


@pytest.mark.parametrize("value", [True, False, None, {"a": 1}, [1], "", "  ", "abc", "1,5"])
def test_price_wrong_types_are_rejected(value: object) -> None:
    reject(unit_price=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"])
def test_price_non_finite_values_are_rejected(value: object) -> None:
    reject(unit_price=value)


def test_price_bound_constant_matches_schema() -> None:
    assert MAX_PRICE == Decimal("99999999.99")


# --- inventory ---------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 20, 2147483647])
def test_inventory_accepts_in_range_integers(value: int) -> None:
    assert parse(inventory=value).inventory == value


@pytest.mark.parametrize("value", [-1, 2147483648, True, False, "5", 5.0, 5.5, None, [1]])
def test_inventory_rejects_bools_strings_floats_and_out_of_range(value: object) -> None:
    reject(inventory=value)


# --- object shape ------------------------------------------------------------


def test_unknown_fields_are_rejected() -> None:
    error = reject(id=1)
    assert "Extra inputs" in error.errors()[0]["msg"]


@pytest.mark.parametrize("field", ["name", "code", "category", "sizes", "unit_price", "inventory", "colors"])
def test_every_field_is_required(field: str) -> None:
    data = valid()
    del data[field]
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(data)


@pytest.mark.parametrize("field", ["name", "code", "category", "sizes", "unit_price", "inventory", "colors"])
def test_null_is_rejected_for_every_field(field: str) -> None:
    reject(**{field: None})


# --- response model ----------------------------------------------------------


def test_read_model_serialises_sorted_arrays_and_decimal_string() -> None:
    read = ProductRead(
        id=1,
        name="Star",
        code="A-001",
        category="cloth",
        sizes=["M", "S"],
        unit_price=Decimal("200.00"),
        inventory=20,
        colors=["Blue", "Red"],
    )
    dumped = read.model_dump(mode="json")
    assert dumped == {
        "id": 1,
        "name": "Star",
        "code": "A-001",
        "category": "cloth",
        "sizes": ["M", "S"],
        "unit_price": "200.00",
        "inventory": 20,
        "colors": ["Blue", "Red"],
    }


def test_sanitize_validation_errors_is_json_serialisable() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse(unit_price=float("nan"))
    safe = sanitize_validation_errors(excinfo.value.errors())
    # This is exactly what Starlette's JSONResponse does: allow_nan=False.
    rendered = json.dumps(safe, allow_nan=False)
    assert "nan" in rendered.lower()


def test_sanitize_validation_errors_preserves_loc_types() -> None:
    # Field names stay strings, list indexes stay integers (FastAPI's own
    # standard detail array keeps them mixed the same way).
    errors = [
        {
            "type": "string_type",
            "loc": ("body", "sizes", 0),
            "msg": "Input should be a valid string",
            "input": 1,
        }
    ]
    item = sanitize_validation_errors(errors)[0]
    assert item["loc"] == ["body", "sizes", 0]
    assert isinstance(item["loc"][2], int) and not isinstance(item["loc"][2], str)
    assert json.dumps(item, allow_nan=False)


def test_sanitize_validation_errors_sanitises_nan_but_keeps_loc() -> None:
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "unit_price"),
            "msg": "Value error, not finite",
            "input": float("nan"),
            "ctx": {"error": ValueError("boom")},
        }
    ]
    item = sanitize_validation_errors(errors)[0]
    assert item["loc"] == ["body", "unit_price"]
    # Only the unsafe leaves are rewritten.
    assert item["input"] == "nan"
    assert item["ctx"] == {"error": "boom"}
    json.dumps(item, allow_nan=False)


def test_invalid_json_body_keeps_integer_offset_in_loc(client: TestClient) -> None:
    response = client.post(
        f"{API}",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["type"] == "json_invalid"
    assert error["loc"][0] == "body"
    assert isinstance(error["loc"][1], int) and not isinstance(error["loc"][1], str)
    assert error["loc"][1] == 1


# --- OpenAPI -----------------------------------------------------------------


def test_docs_and_openapi_are_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_openapi_exposes_the_five_product_operations(openapi: dict) -> None:
    paths = openapi["paths"]
    assert "/api/v1/products" in paths
    assert "/api/v1/products/{product_id}" in paths
    assert set(paths["/api/v1/products"]) == {"get", "post"}
    assert set(paths["/api/v1/products/{product_id}"]) == {"get", "put", "delete"}
    assert paths["/api/v1/products"]["post"]["responses"]["201"]


def test_openapi_request_accepts_string_or_array(openapi: dict) -> None:
    properties = openapi["components"]["schemas"]["ProductCreate"]["properties"]
    for field in ("sizes", "colors"):
        branches = properties[field]["anyOf"]
        assert {"type": "string"} in branches
        assert {"type": "array", "items": {"type": "string"}} in branches
    # unit_price accepts a JSON number or a decimal string.
    price_branches = properties["unit_price"]["anyOf"]
    assert {"type": "number"} in price_branches
    assert {"type": "string"} in price_branches
    assert set(openapi["components"]["schemas"]["ProductCreate"]["required"]) == {
        "name",
        "code",
        "category",
        "sizes",
        "unit_price",
        "inventory",
        "colors",
    }
    assert (
        openapi["components"]["schemas"]["ProductCreate"]["additionalProperties"] is False
    )


def test_openapi_response_uses_arrays_and_decimal_string(openapi: dict) -> None:
    read = openapi["components"]["schemas"]["ProductRead"]["properties"]
    for field in ("sizes", "colors"):
        assert read[field]["type"] == "array"
        assert "anyOf" not in read[field]
    assert read["unit_price"]["type"] == "string"
    assert read["inventory"]["type"] == "integer"
    assert set(read) == {
        "id",
        "name",
        "code",
        "category",
        "sizes",
        "unit_price",
        "inventory",
        "colors",
    }


# --- HTTP-level 422 stays JSON ------------------------------------------------


def test_nan_price_over_http_is_422_json_not_500(client: TestClient) -> None:
    # `json=` would refuse to build this body, so send the raw literal the way
    # a non-strict JSON writer would.
    body = json.dumps(valid(unit_price=float("nan")))
    assert "NaN" in body
    response = client.post(
        f"{API}", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert "nan" in response.text.lower()
    assert "://" not in response.text


def test_infinity_price_over_http_is_422_json_not_500(client: TestClient) -> None:
    body = json.dumps(valid(unit_price=float("inf")))
    assert "Infinity" in body
    response = client.post(
        f"{API}", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert "://" not in response.text
