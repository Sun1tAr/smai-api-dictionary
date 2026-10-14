import os
import subprocess

import httpx
import pytest
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


async def test_names_are_unique_and_ids_are_not_generated(app) -> None:
    async with app.state.session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("INSERT INTO diet (id, name) VALUES (99, 'Веган')")
            )
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("INSERT INTO diet (name) VALUES ('Новая')"))


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


async def test_read_uses_a_read_only_repeatable_read_transaction(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dictionary.repository as repository

    seen: list[tuple[str, str]] = []
    original = repository._load

    async def spy(session, model):
        read_only = await session.scalar(text("SHOW transaction_read_only"))
        isolation = await session.scalar(text("SHOW transaction_isolation"))
        seen.append((read_only, isolation))
        return await original(session, model)

    monkeypatch.setattr(repository, "_load", spy)
    await repository.load_dictionaries(app.state.session_factory)
    assert seen == [("on", "repeatable read")] * 4


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


def test_downgrade_removes_tables_and_upgrade_restores_them(
    alembic_env: dict[str, str],
) -> None:
    alembic(alembic_env, "downgrade", "base")
    alembic(alembic_env, "upgrade", "head")
    alembic(alembic_env, "check")
    alembic(alembic_env, "downgrade", "base")
