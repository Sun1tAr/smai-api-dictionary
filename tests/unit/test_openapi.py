import httpx
import jsonschema
import pytest
from fakes import unavailable_db_settings


@pytest.fixture
async def app():
    from dictionary.main import create_app

    app = create_app(unavailable_db_settings())
    yield app
    await app.state.engine.dispose()
    app.state.tracer_provider.shutdown()


async def test_docs_and_schema_are_served(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
    assert docs.status_code == 200
    assert schema.status_code == 200
    document = schema.json()
    assert document["info"]["title"] == "SmartMeal dictionary service"
    assert document["info"]["version"] == "0.1.0"
    assert document["info"]["description"]


async def test_health_is_fully_documented_and_metrics_is_hidden(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        document = (await client.get("/openapi.json")).json()
    assert set(document["paths"]) == {"/dictionaries", "/health"}
    operation = document["paths"]["/health"]["get"]
    assert operation["summary"]
    assert operation["description"]
    assert set(operation["responses"]) == {"200", "503"}
    ok = operation["responses"]["200"]["content"]["application/json"]
    error = operation["responses"]["503"]["content"]["application/json"]
    assert error["example"]["error"]["code"] == "INTERNAL_ERROR"
    schemas = document["components"]["schemas"]
    health_schema = schemas["HealthResponse"]
    assert health_schema["example"] == {"status": "ok"}
    assert ok["schema"]["$ref"].endswith("/HealthResponse")
    assert error["schema"]["$ref"].endswith("/ErrorResponse")
    # Примеры должны соответствовать собственным схемам.
    jsonschema.validate(health_schema["example"], health_schema)
    error_schema = schemas["ErrorResponse"]
    jsonschema.validate(
        error["example"], {**error_schema, "components": {"schemas": schemas}}
    )


async def test_dictionaries_endpoint_is_fully_documented(app) -> None:
    from spec_data import RESPONSE

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        document = (await client.get("/openapi.json")).json()
    assert set(document["paths"]["/dictionaries"]) == {"get"}
    operation = document["paths"]["/dictionaries"]["get"]
    assert operation["summary"] and operation["description"]
    assert operation["tags"] == ["dictionaries"]
    assert not operation.get("parameters")
    # Валидация здесь недостижима, 422 фреймворка в схеме не нужен.
    assert set(operation["responses"]) == {"200", "500"}
    ok = operation["responses"]["200"]["content"]["application/json"]
    error = operation["responses"]["500"]["content"]["application/json"]
    assert ok["schema"]["$ref"].endswith("/DictionariesResponse")
    assert error["schema"]["$ref"].endswith("/ErrorResponse")
    assert error["example"]["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Failed to load dictionaries",
        "details": {},
    }
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    response_schema = schemas["DictionariesResponse"]
    # Имена полей как в API-7, включая kitchenTools.
    assert set(response_schema["properties"]) == set(RESPONSE)
    assert set(response_schema["required"]) == set(RESPONSE)
    for name in RESPONSE:
        assert response_schema["properties"][name]["description"]
    item_schema = schemas["DictionaryItem"]
    assert set(item_schema["required"]) == {"id", "name"}
    assert item_schema["properties"]["id"]["type"] == "integer"
    # Пример совпадает с контрактом API-7 и со своей схемой.
    assert response_schema["example"] == RESPONSE
    resolver = {"components": {"schemas": schemas}}
    jsonschema.validate(response_schema["example"], {**response_schema, **resolver})
    error_schema = schemas["ErrorResponse"]
    jsonschema.validate(error["example"], {**error_schema, **resolver})
