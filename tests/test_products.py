"""Product API integration tests against the dedicated PostgreSQL database.

The client fixture overrides the ``get_session`` dependency with one Session per
request bound to the guarded test database (``tests/conftest.py``). No CRUD
behaviour is mocked: only the 503/500 tests inject a failure, and even those use
the real application and handlers.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session
from app.main import app
from app.models import Product
from app.schemas import ProductCreate
from app.seed import seed
from app.services import products as product_service

API = "/api/v1/products"


def payload(**overrides: object) -> dict[str, object]:
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


def query_scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def query_all(engine: Engine, sql: str, **params: object) -> list[tuple]:
    with engine.connect() as connection:
        return list(connection.execute(text(sql), params).all())


@pytest.fixture()
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def client(db_engine: Engine, session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A TestClient whose dependency yields one test Session per request."""

    def override_get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create(client: TestClient, **overrides: object) -> dict:
    response = client.post(API, json=payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def run_concurrently(targets: list[Callable[[], None]]) -> None:
    """Run the callables in threads, re-raising any captured exception."""
    errors: list[BaseException] = []

    def guard(target: Callable[[], None]) -> Callable[[], None]:
        def inner() -> None:
            try:
                target()
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        return inner

    threads = [threading.Thread(target=guard(target)) for target in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors


# --- create / read -----------------------------------------------------------


def test_create_returns_201_with_location_and_sorted_output(client: TestClient) -> None:
    response = client.post(API, json=payload())
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert response.headers["location"] == f"/api/v1/products/{body['id']}"
    assert body == {
        "id": body["id"],
        "name": "Star",
        "code": "A-001",
        "category": "cloth",
        "sizes": ["M", "S"],
        "unit_price": "200.00",
        "inventory": 20,
        "colors": ["Blue", "Red"],
    }


def test_get_round_trips_the_created_product(client: TestClient) -> None:
    created = create(client)
    response = client.get(f"{API}/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created
    assert response.headers["content-type"].startswith("application/json")


def test_get_unknown_product_returns_404(client: TestClient) -> None:
    response = client.get(f"{API}/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "1.5", "2147483648", "99999999999999999999"])
def test_invalid_product_id_returns_422(client: TestClient, bad_id: str) -> None:
    for response in (
        client.get(f"{API}/{bad_id}"),
        client.delete(f"{API}/{bad_id}"),
        client.put(f"{API}/{bad_id}", json=payload()),
    ):
        assert response.status_code == 422, (bad_id, response.text)


def test_duplicate_code_returns_409(client: TestClient) -> None:
    create(client)
    response = client.post(API, json=payload(name="Other"))
    assert response.status_code == 409
    assert response.json() == {"detail": "Product code already exists"}


def test_attribute_labels_are_case_sensitive(client: TestClient, db_engine: Engine) -> None:
    first = create(client, code="A-001", colors=["Blue"], category="cloth")
    second = create(client, code="A-002", name="Moon", colors=["blue"], category="Cloth")
    assert first["colors"] == ["Blue"]
    assert second["colors"] == ["blue"]
    assert query_scalar(db_engine, "SELECT count(*) FROM colors") == 2
    assert query_scalar(db_engine, "SELECT count(*) FROM categories") == 2


def test_code_format_is_not_restricted(client: TestClient) -> None:
    body = create(client, code="weird code_1/2")
    assert body["code"] == "weird code_1/2"
    assert client.get(f"{API}/{body['id']}").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        payload(id=1),
        payload(name=None),
        payload(colors=[]),
        payload(inventory=True),
        payload(unit_price="200.001"),
        {k: v for k, v in payload().items() if k != "code"},
    ],
)
def test_invalid_body_returns_422(client: TestClient, body: dict) -> None:
    response = client.post(API, json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_parse_failure_writes_nothing(client: TestClient, db_engine: Engine) -> None:
    response = client.post(API, json=payload(colors="Blue、、Red"))
    assert response.status_code == 422
    assert query_scalar(db_engine, "SELECT count(*) FROM products") == 0
    assert query_scalar(db_engine, "SELECT count(*) FROM colors") == 0
    assert query_scalar(db_engine, "SELECT count(*) FROM categories") == 0


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {},
        {"content": b"{not json", "headers": {"content-type": "application/json"}},
        {"json": [1, 2, 3]},
        {"json": "hello"},
    ],
)
def test_malformed_request_bodies_return_422(client: TestClient, request_kwargs: dict) -> None:
    response = client.post(API, **request_kwargs)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert "://" not in response.text


def test_string_input_creates_the_same_product_as_array(
    client: TestClient, db_engine: Engine
) -> None:
    from_array = create(client, code="A-001", sizes=["S", "M"], colors=["Red", "Blue"])
    from_string = create(client, code="A-002", name="Moon", sizes="S、M", colors="Blue、Red")
    assert from_string["sizes"] == from_array["sizes"] == ["M", "S"]
    assert from_string["colors"] == from_array["colors"] == ["Blue", "Red"]
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes") == 2
    assert query_scalar(db_engine, "SELECT count(*) FROM colors") == 2
    assert query_scalar(db_engine, "SELECT count(*) FROM product_sizes") == 4


def test_price_and_inventory_boundaries_persist(client: TestClient) -> None:
    low = create(client, code="A-001", unit_price=0, inventory=0)
    assert low["unit_price"] == "0.00"
    assert low["inventory"] == 0
    high = create(client, code="A-002", unit_price="99999999.99", inventory=2147483647)
    assert high["unit_price"] == "99999999.99"
    assert high["inventory"] == 2147483647
    trailing = create(client, code="A-003", unit_price="200.000")
    assert trailing["unit_price"] == "200.00"


# --- list --------------------------------------------------------------------


def test_list_is_ordered_and_paginated(client: TestClient) -> None:
    for index in range(5):
        create(client, code=f"C-{index}", name=f"P{index}")

    first = client.get(API, params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == 5
    assert page["limit"] == 2 and page["offset"] == 0
    ids = [item["id"] for item in page["items"]]
    assert ids == sorted(ids)
    assert len(ids) == 2

    last = client.get(API, params={"limit": 2, "offset": 4}).json()
    assert [item["id"] for item in last["items"]] == [max(ids) + 3]

    beyond = client.get(API, params={"limit": 2, "offset": 99}).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5


def test_list_defaults(client: TestClient) -> None:
    create(client)
    page = client.get(API).json()
    assert page["limit"] == 20 and page["offset"] == 0 and page["total"] == 1


def test_multivalued_product_is_listed_once(client: TestClient) -> None:
    create(client, sizes=["S", "M", "L"], colors=["Red", "Blue", "Green"])
    page = client.get(API).json()
    assert page["total"] == 1
    assert len(page["items"]) == 1


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 100001}, {"limit": "x"}],
)
def test_pagination_bounds_return_422(client: TestClient, params: dict) -> None:
    assert client.get(API, params=params).status_code == 422


def test_pagination_upper_bounds_are_allowed(client: TestClient) -> None:
    assert client.get(API, params={"limit": 100, "offset": 100000}).status_code == 200


# --- update ------------------------------------------------------------------


def test_put_replaces_every_field_and_keeps_id(
    client: TestClient, db_engine: Engine
) -> None:
    created = create(client, sizes=["S"], colors=["Red"])
    response = client.put(
        f"{API}/{created['id']}",
        json=payload(
            name="Superstar",
            code="A-777",
            category="pants",
            sizes=["L"],
            unit_price="12.34",
            inventory=7,
            colors=["Green"],
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["code"] == "A-777"
    assert body["name"] == "Superstar"
    assert body["category"] == "pants"
    assert body["sizes"] == ["L"]
    assert body["colors"] == ["Green"]
    assert body["unit_price"] == "12.34"
    assert client.get(f"{API}/{created['id']}").json() == body
    # The old mappings are gone; the shared dictionary rows remain.
    assert query_scalar(
        db_engine,
        "SELECT count(*) FROM product_sizes WHERE product_id = :pid",
        pid=created["id"],
    ) == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes") == 2


def test_put_keeps_shared_attributes_and_other_products(
    client: TestClient, db_engine: Engine
) -> None:
    first = create(client, code="A-001", sizes=["S", "M"], colors=["Red"])
    second = create(client, code="A-002", name="Moon", sizes=["S"], colors=["Red"])

    client.put(
        f"{API}/{second['id']}",
        json=payload(code="A-002", name="Moon", sizes=["L"], colors=["Blue"]),
    )

    assert client.get(f"{API}/{first['id']}").json()["sizes"] == ["M", "S"]
    assert client.get(f"{API}/{first['id']}").json()["colors"] == ["Red"]
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes WHERE code = 'S'") == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM products") == 2


def test_put_unknown_product_returns_404_and_does_not_create(
    client: TestClient, db_engine: Engine
) -> None:
    response = client.put(f"{API}/424242", json=payload())
    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}
    assert query_scalar(db_engine, "SELECT count(*) FROM products") == 0
    assert query_scalar(db_engine, "SELECT count(*) FROM categories") == 0


def test_put_code_conflict_rolls_back_including_new_attributes(
    client: TestClient, db_engine: Engine
) -> None:
    create(client, code="A-001")
    other = create(client, code="A-002", name="Moon", sizes=["L"], colors=["Green"])

    response = client.put(
        f"{API}/{other['id']}",
        json=payload(
            name="Moon",
            code="A-001",  # collides with the first product
            category="brand-new-category",
            sizes=["XL"],
            colors=["Ultraviolet"],
            inventory=3,
        ),
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Product code already exists"}

    # The original product is untouched...
    assert client.get(f"{API}/{other['id']}").json() == other
    # ...and the attributes created for the failed request are gone.
    assert query_scalar(
        db_engine, "SELECT count(*) FROM categories WHERE name = 'brand-new-category'"
    ) == 0
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes WHERE code = 'XL'") == 0
    assert query_scalar(
        db_engine, "SELECT count(*) FROM colors WHERE name = 'Ultraviolet'"
    ) == 0


def test_put_invalid_body_returns_422_and_changes_nothing(client: TestClient) -> None:
    created = create(client)
    response = client.put(
        f"{API}/{created['id']}", json={k: v for k, v in payload().items() if k != "colors"}
    )
    assert response.status_code == 422
    assert client.get(f"{API}/{created['id']}").json() == created


# --- delete ------------------------------------------------------------------


def test_delete_returns_204_with_empty_body_then_get_404(
    client: TestClient, db_engine: Engine
) -> None:
    created = create(client)
    response = client.delete(f"{API}/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"{API}/{created['id']}").status_code == 404
    assert query_scalar(db_engine, "SELECT count(*) FROM product_sizes") == 0
    assert query_scalar(db_engine, "SELECT count(*) FROM product_colors") == 0


def test_delete_keeps_shared_attributes_and_other_products(
    client: TestClient, db_engine: Engine
) -> None:
    first = create(client, code="A-001", sizes=["S"], colors=["Red"])
    create(client, code="A-002", name="Moon", sizes=["S"], colors=["Red"])

    assert client.delete(f"{API}/{first['id']}").status_code == 204
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes") == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM colors") == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM products") == 1


def test_delete_unknown_product_returns_404(client: TestClient) -> None:
    assert client.delete(f"{API}/123").status_code == 404


# --- seed --------------------------------------------------------------------


def test_seed_creates_four_products_and_is_idempotent(
    session_factory: sessionmaker[Session], client: TestClient
) -> None:
    with session_factory() as session:
        assert seed(session) == (4, 0)
    with session_factory() as session:
        assert seed(session) == (0, 4)

    page = client.get(API).json()
    assert page["total"] == 4
    by_code = {item["code"]: item for item in page["items"]}
    assert set(by_code) == {"A-001", "A-002", "B-001", "B-002"}
    assert by_code["A-001"]["sizes"] == ["M", "S"]
    assert by_code["A-001"]["colors"] == ["Blue", "Red"]
    assert by_code["A-001"]["unit_price"] == "200.00"
    assert by_code["B-002"] == {
        "id": by_code["B-002"]["id"],
        "name": "Bird",
        "code": "B-002",
        "category": "pants",
        "sizes": ["L", "M", "S"],
        "unit_price": "50.00",
        "inventory": 12,
        "colors": ["Black"],
    }


def test_seed_does_not_overwrite_a_modified_product(
    session_factory: sessionmaker[Session], client: TestClient
) -> None:
    with session_factory() as session:
        assert seed(session) == (4, 0)

    star = next(item for item in client.get(API).json()["items"] if item["code"] == "A-001")
    client.put(
        f"{API}/{star['id']}",
        json=payload(name="Changed", code="A-001", unit_price="1.00", inventory=1, sizes=["XS"], colors=["Pink"]),
    )

    with session_factory() as session:
        assert seed(session) == (0, 4)

    assert client.get(f"{API}/{star['id']}").json() == {
        "id": star["id"],
        "name": "Changed",
        "code": "A-001",
        "category": "cloth",
        "sizes": ["XS"],
        "unit_price": "1.00",
        "inventory": 1,
        "colors": ["Pink"],
    }


def test_seed_returns_nothing_to_do_on_empty_database(client: TestClient) -> None:
    assert client.get(API).json()["total"] == 0


# --- concurrency -------------------------------------------------------------


def test_concurrent_same_attribute_creation_stays_unique(
    session_factory: sessionmaker[Session], db_engine: Engine
) -> None:
    barrier = threading.Barrier(2, timeout=15)
    created: list[int] = []

    def make(number: int) -> None:
        data = ProductCreate.model_validate(
            payload(
                name=f"P{number}",
                code=f"S-{number}",
                category="fresh-category",
                sizes=["XS"],
                colors=["Teal"],
            )
        )
        with session_factory() as session:
            barrier.wait()
            created.append(product_service.create_product(session, data).id)

    run_concurrently([lambda: make(0), lambda: make(1)])

    assert len(set(created)) == 2
    assert query_scalar(
        db_engine, "SELECT count(*) FROM categories WHERE name = 'fresh-category'"
    ) == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM sizes WHERE code = 'XS'") == 1
    assert query_scalar(db_engine, "SELECT count(*) FROM colors WHERE name = 'Teal'") == 1
    category_ids = query_all(
        db_engine,
        "SELECT DISTINCT category_id FROM products WHERE code IN ('S-0', 'S-1')",
    )
    assert len(category_ids) == 1


def test_concurrent_replacement_does_not_mix_collections(
    session_factory: sessionmaker[Session], client: TestClient
) -> None:
    target = create(client, code="A-001", sizes=["S"], colors=["Red"])
    first = ProductCreate.model_validate(
        payload(code="A-001", sizes=["S", "M"], colors=["Red", "Blue"])
    )
    second = ProductCreate.model_validate(
        payload(code="A-001", sizes=["L"], colors=["Green"])
    )
    barrier = threading.Barrier(2, timeout=15)

    def replace(data: ProductCreate) -> None:
        with session_factory() as session:
            barrier.wait()
            product_service.update_product(session, target["id"], data)

    run_concurrently([lambda: replace(first), lambda: replace(second)])

    with session_factory() as session:
        product = session.get(Product, target["id"])
        assert product is not None
        result = (
            tuple(sorted(size.code for size in product.sizes)),
            tuple(sorted(color.name for color in product.colors)),
        )
    assert result in ((("M", "S"), ("Blue", "Red")), (("L",), ("Green",)))


# --- error handling ----------------------------------------------------------


def test_database_unavailable_returns_503(client: TestClient) -> None:
    def failing_session() -> Iterator[Session]:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        yield  # pragma: no cover - makes this a generator

    app.dependency_overrides[get_session] = failing_session
    response = client.get(API)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_unexpected_error_returns_safe_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("internal detail: SELECT * FROM products")

    monkeypatch.setattr(product_service, "list_products", explode)
    response = client.get(API)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "SELECT" not in response.text
    assert "://" not in response.text
    assert "Traceback" not in response.text


def test_error_bodies_do_not_leak_connection_details(client: TestClient) -> None:
    bodies = [
        client.post(API, json=payload(colors="")),
        client.get(f"{API}/999999"),
        client.delete(f"{API}/999999"),
    ]
    for response in bodies:
        text = response.text
        assert "://" not in text
        assert "postgresql" not in text.lower()
        assert "Traceback" not in text


def test_only_the_code_unique_violation_is_a_conflict() -> None:
    def integrity_error(constraint_name: str | None, message: str = "") -> IntegrityError:
        diag = type("Diag", (), {"constraint_name": constraint_name})()

        class Orig:
            def __init__(self) -> None:
                self.diag = diag

            def __str__(self) -> str:
                return message

        return IntegrityError("INSERT INTO products ...", {}, Orig())

    assert product_service.is_code_conflict(integrity_error("uq_products_code")) is True
    assert product_service.is_code_conflict(integrity_error("uq_categories_name")) is False
    assert product_service.is_code_conflict(integrity_error(None)) is False
    assert (
        product_service.is_code_conflict(
            integrity_error(None, "duplicate key ... uq_products_code")
        )
        is True
    )


def test_openapi_document_is_reachable_through_the_client(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert json.loads(json.dumps(spec))["info"]["title"]
    assert "/api/v1/products" in spec["paths"]
