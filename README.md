# smai-api-dictionary

MS-2 — сервис справочников SmartMeal (SMAI-86). Хранит четыре фиксированных
справочника (пищевые привычки, диеты, аллергены, кухонная техника) и отдаёт их
клиенту одним запросом (API-7). Клиент обращается к сервису через gateway.

Справочники — сид-данные миграции Alembic (LE-7…LE-10): `id` стабилен, `name`
уникален внутри справочника, административного CRUD нет. Сервис не хранит
пользовательский выбор.

## Эндпоинты

Интерактивная документация (Swagger UI) — `/docs`, схема OpenAPI — `/openapi.json`.

| Метод и путь | Назначение | Ответы | Статус |
| --- | --- | --- | --- |
| `GET /dictionaries` | Все справочники одним ответом (API-7): `habits`, `diets`, `allergies`, `kitchenTools`; элементы `{id, name}` по возрастанию `id` | 200, 500 `INTERNAL_ERROR` | API-7 |
| `GET /health` | Готовность: `SELECT 1` к PostgreSQL; не пишет спаны; успешный ответ логируется на DEBUG, 503 — на INFO | 200 `{"status":"ok"}`, 503 `INTERNAL_ERROR` | служебный |
| `GET /metrics` | Метрики Prometheus: HTTP, Python, GC и процесс (вне схемы OpenAPI); успешный ответ логируется на DEBUG, ошибки — на INFO | 200 `text/plain` | служебный |
| `GET /docs` | Swagger UI | 200 `text/html` | служебный |
| `GET /openapi.json` | Схема OpenAPI | 200 `application/json` | служебный |

Пример ответа `GET /dictionaries` (сокращён; полный пример с 45 значениями — в
`/docs`):

```json
{
  "habits": [{"id": 1, "name": "Быстрые перекусы"}],
  "diets": [{"id": 1, "name": "Веган"}],
  "allergies": [{"id": 1, "name": "Глютен"}],
  "kitchenTools": [{"id": 1, "name": "Плита"}]
}
```

Параметров нет; лишние query-параметры игнорируются. Четыре справочника
читаются одним согласованным снимком БД (транзакция `REPEATABLE READ READ ONLY`).

Все ошибки возвращаются в одном формате (без префикса `/api/v1` и без обёртки
`data`/`meta`):

```json
{"error": {"code": "INTERNAL_ERROR", "message": "Failed to load dictionaries", "details": {}}}
```

Коды: `INTERNAL_ERROR` (500 при ошибке чтения справочников или необработанном
исключении, 503 на `/health`), `NOT_FOUND` (404), `METHOD_NOT_ALLOWED` (405),
`VALIDATION_ERROR` (400, общий обработчик; на `GET /dictionaries` недостижим).
404 и 405 общие для всего сервиса и в схеме отдельных эндпоинтов не повторяются.
Каждый ответ, включая 500, содержит заголовок `X-Request-ID`: входящее значение
принимается, если это до 128 символов `A-Za-z0-9._-`, иначе генерируется UUID4;
тот же `request_id` пишется в логи. Тексты исключений и SQL в ответы и логи не
попадают. Схема OpenAPI не содержит `422` и `HTTPValidationError` фреймворка.

## Локальный запуск

Требуются Docker и Docker Compose. Сервис подключается к внешней сети `smai`,
общей для контура (gateway находит его по имени `dictionary`).

```sh
docker network create smai   # один раз
cp .env.example .env         # проверьте значения, это локальные заглушки
docker compose up --build --wait
curl --fail http://127.0.0.1:8002/dictionaries
curl --fail http://127.0.0.1:8002/health
curl --fail http://127.0.0.1:8002/docs
docker compose down -v       # остановка; -v удаляет том PostgreSQL
```

Контейнер слушает `0.0.0.0:8000`, на хосте порт публикуется как
`127.0.0.1:${DICTIONARY_HTTP_PORT:-8002}`. PostgreSQL доступен только внутри
Compose-сети. При старте контейнер выполняет `alembic upgrade head` (создаёт
таблицы и наполняет справочники), затем запускает uvicorn; приложение не
стартует, если БД недоступна. Контейнер работает от пользователя `dictionary`
(UID 10001).

## Конфигурация

Настройки читаются только из окружения (локально — также из `.env` в рабочей
директории; переменные процесса приоритетнее). Пустое значение (`KEY=`)
считается незаданным. Некорректная конфигурация останавливает запуск.

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Подключение к PostgreSQL | Обязательны |
| `DB_PORT` | Порт PostgreSQL | `5432` |
| `DB_TIMEOUT_SECONDS` | Предельное ожидание БД (0, 60]: подключение и запросы приложения. Запросы миграций не ограничиваются | `5` |
| `MIGRATION_LOCK_TIMEOUT_SECONDS` | Ожидание чужой блокировки при миграциях, (0, 3600] | `30` |
| `LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR | `INFO` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Базовый адрес OTLP HTTP, например `http://collector:4318` | Экспорт отключён |
| `DICTIONARY_HTTP_PORT` | Только Compose: порт на хосте | `8002` |

## Миграции и данные

Таблицы `habit`, `diet`, `allergen`, `kitchen_tool` (`id` — целое без identity/
serial, `name` — уникальная строка) и их значения создаёт ревизия `0001`.
Таблица версий Alembic — `alembic_version_dictionary` (общий PostgreSQL на
стенде). Изменение справочника — новой ревизией с явными `id`; `id` существующих
значений не меняются.

## Разработка и тесты

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/unit -p no:cacheprovider -q
# интеграционные тесты на реальном PostgreSQL (как в CI-сценарии)
docker compose -p dictionary-tests -f docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from tests
docker compose -p dictionary-tests -f docker-compose.test.yml down -v
```

Два режима запуска отличаются строгостью:

- `docker-compose.test.yml` запускает все тесты (unit и интеграционные на
  PostgreSQL 17) с `FAIL_ON_SKIP=1` и порогом покрытия `--cov-fail-under=98`.
  `FAIL_ON_SKIP=1` превращает любой пропущенный тест в ошибку, поэтому
  интеграционные тесты не могут молча отключиться, если `TEST_DB_*` не дошли до
  контейнера.
- Локальный `uv run pytest tests/unit` этих ограничений не применяет: нет ни
  `FAIL_ON_SKIP`, ни проверки покрытия, а интеграционные тесты без `TEST_DB_HOST`
  пропускаются.
