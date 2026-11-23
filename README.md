# Smart Meal AI — Dictionary Service (MS-2)

Сервис справочников **Smart Meal AI**. Хранит четыре фиксированных справочника,
которые клиент выбирает при настройке меню, и отдаёт их одним запросом через
gateway.

> **Ветка.** Актуальный код и полная документация сервиса находятся в ветке
> `develop`. В `main` исторически лежит только README; этот файл описывает
> состояние `develop`.

## Роль в системе

MS-2 не хранит пользовательский выбор и не имеет административного CRUD.
Справочники — сид-данные миграции Alembic: `id` стабилен, `name` уникален внутри
справочника. Сервис нужен двум потребителям:

- gateway — для `GET /dictionaries` (API-7);
- MS-4 (`smai-api-receipes`) — для проверки ID и подстановки названий в промпт
  генерации меню.

## Стек

- Python 3.12, FastAPI, Pydantic Settings;
- SQLAlchemy 2 (async) + asyncpg, PostgreSQL;
- Alembic;
- structlog, OpenTelemetry, Prometheus (`prometheus-fastapi-instrumentator`);
- uv, Ruff, pytest, Docker Compose, GitHub Actions.

## API

Интерактивная документация — `/docs`, схема OpenAPI — `/openapi.json`.

| Метод | Путь | Назначение | Ответы |
|---|---|---|---|
| `GET` | `/dictionaries` | Все справочники одним ответом: `habits`, `diets`, `allergies`, `kitchenTools` | 200, 500 |
| `GET` | `/health` | Готовность: `SELECT 1` к PostgreSQL | 200, 503 |
| `GET` | `/metrics` | Метрики Prometheus | 200 |
| `GET` | `/docs`, `/openapi.json` | Swagger UI и схема | 200 |

Пример ответа:

```json
{
  "habits": [{"id": 1, "name": "Быстрые перекусы"}],
  "diets": [{"id": 1, "name": "Веган"}],
  "allergies": [{"id": 1, "name": "Глютен"}],
  "kitchenTools": [{"id": 1, "name": "Плита"}]
}
```

Четыре справочника читаются одним согласованным снимком БД. Параметров у запроса
нет, лишние query-параметры игнорируются.

Ошибки — единый формат без обёртки:

```json
{"error": {"code": "INTERNAL_ERROR", "message": "Failed to load dictionaries", "details": {}}}
```

Каждый ответ содержит `X-Request-ID`; входящее значение принимается, если это до
128 символов `A-Za-z0-9._-`, иначе генерируется UUID4.

## Данные

Таблицы `habit`, `diet`, `allergen`, `kitchen_tool` создаются и наполняются
ревизией `0001_create_dictionaries`. Таблица версий Alembic —
`alembic_version_dictionary`. Изменение справочника выполняется новой ревизией с
явными `id`; существующие `id` не меняются.

## Конфигурация

Настройки читаются из окружения (локально — также из `.env`). Пустое значение
считается незаданным; некорректная конфигурация останавливает запуск.

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Подключение к PostgreSQL | обязательны |
| `DB_PORT` | Порт PostgreSQL | `5432` |
| `DB_TIMEOUT_SECONDS` | Предельное ожидание БД | `5` |
| `MIGRATION_LOCK_TIMEOUT_SECONDS` | Ожидание блокировки при миграциях | `30` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Адрес OTLP HTTP-коллектора | экспорт отключён |
| `DICTIONARY_HTTP_PORT` | Хостовой порт Compose | `8002` |

## Локальный запуск

Нужны Docker и Docker Compose. Сервис подключается к внешней сети `smai`, по
имени `dictionary` его находит gateway.

```sh
docker network create smai   # один раз
cp .env.example .env         # локальные заглушки, проверьте значения
docker compose up --build --wait
curl --fail http://127.0.0.1:8002/dictionaries
curl --fail http://127.0.0.1:8002/health
docker compose down -v
```

Контейнер слушает `0.0.0.0:8000`, на хосте публикуется
`127.0.0.1:${DICTIONARY_HTTP_PORT:-8002}`. При старте выполняется
`alembic upgrade head`, затем запускается uvicorn. Контейнер работает от
пользователя `dictionary` (UID 10001).

## Разработка и тесты

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/unit -p no:cacheprovider -q

# unit + integration на реальном PostgreSQL
docker compose -p dictionary-tests -f docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from tests
docker compose -p dictionary-tests -f docker-compose.test.yml down -v
```

Тестовый Compose запускает все тесты с `FAIL_ON_SKIP=1` и порогом покрытия 98 %,
поэтому интеграционные тесты не могут молча отключиться. CI
(`.github/workflows/ci.yml`) выполняет линтер, unit-тесты, интеграционные тесты и
сборку образа.

## Известные ограничения

- Справочники неизменяемы в рантайме: обновление — только миграцией.
- Нет административного API и авторизации: сервис доступен только из сети
  контура.
- Базовые образы закреплены тегами, а не digest.

## Связанные репозитории

- [SmartMeal-AI](https://github.com/Sun1tAr/SmartMeal-AI) — обзор проекта;
- [smai-api-gateway](https://github.com/Sun1tAr/smai-api-gateway) — публикует `/dictionaries`;
- [smai-api-receipes](https://github.com/Sun1tAr/smai-api-receipes) — использует справочники в генерации;
- [smai-infra](https://github.com/Sun1tAr/smai-infra) — развёртывание контура.
