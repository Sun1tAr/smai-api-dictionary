import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _stage(name: str) -> str:
    dockerfile = (ROOT / "Dockerfile").read_text()
    match = re.search(
        rf"^FROM .* AS {name}$(.*?)(?=^FROM |\Z)", dockerfile, re.MULTILINE | re.DOTALL
    )
    assert match is not None
    return match.group(1)


def test_runtime_starts_application_as_unprivileged_user() -> None:
    runtime = _stage("runtime")
    commands = re.findall(r"^CMD (\[.*\])$", runtime, re.MULTILINE)
    assert json.loads(commands[-1]) == ["python", "-m", "dictionary"]
    assert "--uid 10001" in runtime
    assert re.search(r"^USER dictionary$", runtime, re.MULTILINE)
    assert "EXPOSE 8000" in runtime
    assert "HEALTHCHECK" in runtime and "/health" in runtime


def test_production_stage_exists() -> None:
    assert re.search(
        r"^FROM runtime AS production$", (ROOT / "Dockerfile").read_text(), re.MULTILINE
    )


def test_compose_service_is_named_dictionary_and_publishes_port() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert re.search(r"^  dictionary:$", compose, re.MULTILINE)
    assert '"127.0.0.1:${DICTIONARY_HTTP_PORT:-8002}:8000"' in compose
    # Gateway находит сервис по имени dictionary в общей внешней сети smai.
    assert re.search(r"^  smai:\n    external: true$", compose, re.MULTILINE)
    assert "- dictionary" in compose
    assert "condition: service_healthy" in compose
    assert "postgres:17-alpine" in compose


def test_compose_requires_database_secrets() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    for name in ("DB_NAME", "DB_USER", "DB_PASSWORD"):
        assert f"${{{name}:?" in compose
