import json
import os
import re
import subprocess
import sys
from pathlib import Path


def test_migration_connection_failure_has_safe_logs_and_nonzero_exit() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "1",
            "DB_NAME": "dictionary",
            "DB_USER": "dictionary",
            "DB_PASSWORD": "private-migration-password",
            "DB_TIMEOUT_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "private-migration-password" not in result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    failure = next(item for item in events if item["message"] == "migration_failed")
    assert failure["level"] == "error"
    assert failure["error_type"]
    # Без версии в БД, SQLSTATE и текста сообщения: вывод только безопасных полей.
    assert failure["sqlstate"] is None
    assert "db_message" not in failure
    assert "from_revision" in failure and "last_applied" in failure


def offline_sql(*arguments: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "DB_HOST": "127.0.0.1",
            "DB_NAME": "dictionary",
            "DB_USER": "dictionary",
            "DB_PASSWORD": "offline-only",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_single_head_revision_creates_tables_and_seeds_spec_values() -> None:
    from spec_data import TABLES

    sql = offline_sql("upgrade", "head")
    for table, rows in TABLES.items():
        assert f"CREATE TABLE {table} (" in sql
        assert f"CONSTRAINT pk_{table} PRIMARY KEY (id)" in sql
        assert f"CONSTRAINT uq_{table}_name UNIQUE (name)" in sql
        inserts = re.findall(
            rf"INSERT INTO {table} \(id, name\) VALUES \((\d+), '([^']*)'\)", sql
        )
        assert [(int(row_id), name) for row_id, name in inserts] == rows
    # Никаких sequence/identity: id приходят только из сидов.
    assert "SERIAL" not in sql.upper() and "IDENTITY" not in sql.upper()


def test_migration_history_uses_a_service_specific_version_table() -> None:
    sql = offline_sql("upgrade", "head")
    assert "alembic_version_dictionary" in sql
    assert "alembic_version " not in sql.replace("alembic_version_dictionary", "")


def test_downgrade_drops_the_four_tables() -> None:
    from spec_data import TABLES

    sql = offline_sql("downgrade", "head:base")
    for table in TABLES:
        assert f"DROP TABLE {table};" in sql
