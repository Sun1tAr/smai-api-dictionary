import json

import httpx
import pytest
from fakes import unavailable_db_settings
from spec_data import RESPONSE, as_items


@pytest.fixture
async def app(capsys):
    from dictionary.main import create_app

    app = create_app(unavailable_db_settings())
    yield app
    await app.state.engine.dispose()
    app.state.tracer_provider.shutdown()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


# Приложение настраивает логи до capsys: перенастраиваем вывод на перехват.
def capture_logs() -> None:
    from dictionary.observability import configure_logging

    configure_logging("INFO")


def stub_repository(monkeypatch: pytest.MonkeyPatch, data: dict) -> list[object]:
    import dictionary.api as api
    from dictionary.schemas import DictionariesResponse

    calls: list[object] = []

    async def load(session_factory):
        calls.append(session_factory)
        return DictionariesResponse.model_validate(data)

    monkeypatch.setattr(api, "load_dictionaries", load)
    return calls


async def test_returns_all_four_dictionaries_with_contract_keys(
    client, app, monkeypatch
) -> None:
    calls = stub_repository(monkeypatch, RESPONSE)
    response = await client.get("/dictionaries")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == RESPONSE
    # Ключи ответа ровно как в API-7 (kitchenTools, не kitchen_tools).
    assert set(response.json()) == {"habits", "diets", "allergies", "kitchenTools"}
    assert calls == [app.state.session_factory]


async def test_items_keep_the_order_from_the_repository(client, monkeypatch) -> None:
    data = {**RESPONSE, "habits": as_items([(1, "A"), (2, "B"), (3, "C")])}
    stub_repository(monkeypatch, data)
    payload = (await client.get("/dictionaries")).json()
    assert [item["id"] for item in payload["habits"]] == [1, 2, 3]


async def test_every_item_has_exactly_id_and_name(client, monkeypatch) -> None:
    stub_repository(monkeypatch, RESPONSE)
    payload = (await client.get("/dictionaries")).json()
    for items in payload.values():
        for item in items:
            assert set(item) == {"id", "name"}
            assert isinstance(item["id"], int) and isinstance(item["name"], str)


async def test_unknown_query_parameters_are_ignored(client, monkeypatch) -> None:
    stub_repository(monkeypatch, RESPONSE)
    response = await client.get("/dictionaries?foo=bar")
    assert response.status_code == 200
    assert response.json() == RESPONSE


async def test_repository_failure_returns_500_in_service_format(
    client, monkeypatch, capsys
) -> None:
    import dictionary.api as api

    async def fail(session_factory):
        raise RuntimeError("SELECT secret FROM habit; password=private-db-pass")

    monkeypatch.setattr(api, "load_dictionaries", fail)
    capture_logs()
    response = await client.get("/dictionaries", headers={"X-Request-ID": "req-1"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-1"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Failed to load dictionaries",
            "details": {},
        }
    }
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    failure = next(e for e in events if e["message"] == "dictionaries_load_failed")
    assert failure["level"] == "error"
    assert failure["exception"]["type"] == "RuntimeError"
    assert failure["request_id"] == "req-1"
    assert "private-db-pass" not in output and "SELECT secret" not in output


async def test_unavailable_database_returns_500_not_a_stack_trace(client) -> None:
    # Без подмены репозитория: порт БД закрыт, как при падении PostgreSQL.
    response = await client.get("/dictionaries")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "Failed to load dictionaries"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
async def test_only_get_is_allowed(client, method: str) -> None:
    response = await getattr(client, method)("/dictionaries")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_successful_request_is_logged_at_info_without_query(
    client, monkeypatch, capsys
) -> None:
    stub_repository(monkeypatch, RESPONSE)
    capture_logs()
    await client.get("/dictionaries?secret=private-query")
    # Клиентский лог httpx в тесте содержит URL; проверяем события сервиса.
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    event = next(e for e in events if e["message"] == "http_request")
    assert "private-query" not in json.dumps(event)
    assert event["level"] == "info"
    assert event["path"] == "/dictionaries" and event["status_code"] == 200
