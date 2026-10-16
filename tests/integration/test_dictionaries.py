import os
import subprocess

import httpx
import pytest
from pydantic import SecretStr
from spec_data import RESPONSE, TABLES
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dictionary.config import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DB_HOST"), reason="TEST_DB_HOST is not set"),
]


def alembic(env: dict[str, str], *arguments: str) -> None:
    result = subprocess.run(
        ["alembic", *arguments],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def migrated(alembic_env: dict[str, str]):
    alembic(alembic_env, "downgrade", "base")
    alembic(alembic_env, "upgrade", "head")
    yield
    alembic(alembic_env, "downgrade", "base")


@pytest.fixture
async def app(settings: Settings, migrated):
    from dictionary.main import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_tables_contain_exactly_the_spec_values(app) -> None:
    async with app.state.session_factory() as session:
        for table, rows in TABLES.items():
            result = await session.execute(
                text(f"SELECT id, name FROM {table} ORDER BY id")
            )
            assert [tuple(row) for row in result] == rows


async def test_tables_have_primary_key_unique_name_and_no_identity(app) -> None:
    async with app.state.session_factory() as session:
        for table in TABLES:
            constraints = await session.execute(
                text(
                    "SELECT conname, CAST(contype AS text) FROM pg_constraint "
                    "WHERE conrelid = CAST(:table AS regclass) ORDER BY conname"
                ),
                {"table": table},
            )
            assert [tuple(row) for row in constraints] == [
                (f"pk_{table}", "p"),
                (f"uq_{table}_name", "u"),
            ]
            column = await session.execute(
                text(
                    "SELECT is_identity, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = 'id'"
                ),
                {"table": table},
            )
            assert tuple(column.one()) == ("NO", None)


async def test_version_table_is_service_specific(app) -> None:
    async with app.state.session_factory() as session:
        version = await session.scalar(
            text("SELECT version_num FROM alembic_version_dictionary")
        )
        legacy = await session.scalar(text("SELECT to_regclass('alembic_version')"))
    assert version == "0001"
    assert legacy is None


async def test_upgrade_is_repeatable_and_does_not_duplicate_seeds(
    app, alembic_env: dict[str, str]
) -> None:
    alembic(alembic_env, "upgrade", "head")
    async with app.state.session_factory() as session:
        for table, rows in TABLES.items():
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == len(
                rows
            )


async def sqlstate_of_failed(app, statement: str) -> str:
    async with app.state.session_factory() as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(text(statement))
        await session.rollback()
    return error.value.orig.sqlstate


async def test_names_are_unique_and_ids_are_not_generated(app) -> None:
    # 23505 unique_violation, 23502 not_null_violation (id не генерируется БД).
    assert (
        await sqlstate_of_failed(
            app, "INSERT INTO diet (id, name) VALUES (99, 'Веган')"
        )
        == "23505"
    )
    assert await sqlstate_of_failed(
        app, "INSERT INTO diet (name) VALUES ('Новая')"
    ) == ("23502")
    assert (
        await sqlstate_of_failed(
            app, "INSERT INTO diet (id, name) VALUES (1, 'Другая')"
        )
        == "23505"
    )


async def test_endpoint_returns_the_api_7_response_from_the_database(client) -> None:
    response = await client.get("/dictionaries")
    assert response.status_code == 200
    assert response.json() == RESPONSE
    # Порядок ключей и элементов детерминирован.
    assert list(response.json()) == ["habits", "diets", "allergies", "kitchenTools"]


async def test_endpoint_orders_by_id_regardless_of_insertion_order(app, client) -> None:
    async with app.state.session_factory() as session:
        await session.execute(text("DELETE FROM diet WHERE id = 1"))
        await session.execute(text("INSERT INTO diet (id, name) VALUES (1, 'Веган')"))
        await session.commit()
    payload = (await client.get("/dictionaries")).json()
    assert [item["id"] for item in payload["diets"]] == [1, 2, 3, 4]


async def test_read_uses_one_read_only_repeatable_read_transaction(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dictionary.repository as repository

    seen: list[tuple[str, str, int, object]] = []
    original = repository._load

    async def spy(session, model):
        read_only = await session.scalar(text("SHOW transaction_read_only"))
        isolation = await session.scalar(text("SHOW transaction_isolation"))
        backend = await session.scalar(text("SELECT pg_backend_pid()"))
        started = await session.scalar(text("SELECT transaction_timestamp()"))
        seen.append((read_only, isolation, backend, started))
        return await original(session, model)

    monkeypatch.setattr(repository, "_load", spy)
    await repository.load_dictionaries(app.state.session_factory)
    assert len(seen) == 4
    assert {(row[0], row[1]) for row in seen} == {("on", "repeatable read")}
    # Одно соединение и одна транзакция на все четыре справочника.
    assert len({row[2] for row in seen}) == 1
    assert len({row[3] for row in seen}) == 1


async def test_missing_tables_give_500_in_service_format(
    app, client, alembic_env: dict[str, str]
) -> None:
    async with app.state.session_factory() as session:
        await session.execute(text("ALTER TABLE habit RENAME TO habit_gone"))
        await session.commit()
    try:
        response = await client.get("/dictionaries")
    finally:
        async with app.state.session_factory() as session:
            await session.execute(text("ALTER TABLE habit_gone RENAME TO habit"))
            await session.commit()
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Failed to load dictionaries",
            "details": {},
        }
    }


async def existing_tables(settings: Settings) -> set[str]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


async def row_counts(settings: Settings) -> dict[str, int]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            return {
                table: await connection.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in TABLES
            }
    finally:
        await engine.dispose()


async def version_rows(settings: Settings) -> int | None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            if "alembic_version_dictionary" not in await existing_tables(settings):
                return None
            return await connection.scalar(
                text("SELECT count(*) FROM alembic_version_dictionary")
            )
    finally:
        await engine.dispose()


async def test_downgrade_removes_tables_and_upgrade_restores_seeded_tables(
    settings: Settings, alembic_env: dict[str, str]
) -> None:
    expected_counts = {table: len(rows) for table, rows in TABLES.items()}
    try:
        # Начинаем с заведомо применённой ревизии, чтобы downgrade что-то делал.
        alembic(alembic_env, "downgrade", "base")
        alembic(alembic_env, "upgrade", "head")
        assert set(TABLES) <= await existing_tables(settings)
        assert await row_counts(settings) == expected_counts
        assert await version_rows(settings) == 1

        alembic(alembic_env, "downgrade", "base")
        # Таблица версий Alembic остаётся, но пуста; справочников нет.
        assert set(TABLES) & await existing_tables(settings) == set()
        assert await version_rows(settings) in (None, 0)

        alembic(alembic_env, "upgrade", "head")
        assert await row_counts(settings) == expected_counts
        assert await version_rows(settings) == 1
    finally:
        alembic(alembic_env, "downgrade", "base")


async def test_health_is_ok_on_debug_and_503_when_database_rejects_the_service(
    app,
    client,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from dictionary.main import create_app
    from dictionary.observability import configure_logging

    configure_logging("DEBUG")
    assert (await client.get("/health")).status_code == 200
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    ok = next(e for e in events if e["message"] == "http_request")
    assert (ok["path"], ok["status_code"], ok["level"]) == ("/health", 200, "debug")

    capsys.readouterr()
    # PostgreSQL доступен, но отвергает учётные данные: сервис не готов.
    broken = create_app(
        settings.model_copy(
            update={"db_password": SecretStr("wrong-password"), "log_level": "DEBUG"}
        )
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=broken), base_url="http://test"
        ) as broken_client:
            response = await broken_client.get("/health")
    finally:
        await broken.state.engine.dispose()
        broken.state.tracer_provider.shutdown()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "wrong-password" not in response.text
    # create_app настраивает логи на stdout (DEBUG): туда попадают и записи
    # SQLAlchemy/asyncpg; пароль не должен появиться ни в одной из них.
    captured = capsys.readouterr()
    logs = captured.out + captured.err
    assert "dependency_unavailable" in logs
    assert "wrong-password" not in logs
