import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from dictionary.errors import ErrorResponse, error_response
from dictionary.repository import load_dictionaries
from dictionary.schemas import DictionariesResponse

router = APIRouter()
logger = structlog.get_logger()


@router.get(
    "/dictionaries",
    tags=["dictionaries"],
    summary="Получение справочников (API-7)",
    description=(
        "Возвращает одним ответом четыре фиксированных справочника для экранов "
        "параметров: пищевые привычки (`habits`), диеты (`diets`), аллергены "
        "(`allergies`) и кухонную технику (`kitchenTools`). Каждый элемент — "
        "`{id, name}`; `id` стабилен, элементы упорядочены по `id`. Параметров "
        "нет, лишние query-параметры игнорируются. Данные читаются одним "
        "согласованным снимком БД."
    ),
    response_model=DictionariesResponse,
    responses={
        500: {
            "model": ErrorResponse,
            "description": "Ошибка при получении справочников, например БД недоступна.",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "Failed to load dictionaries",
                            "details": {},
                        }
                    }
                }
            },
        }
    },
)
async def get_dictionaries(request: Request) -> DictionariesResponse | JSONResponse:
    try:
        return await load_dictionaries(request.app.state.session_factory)
    except Exception:
        # Стек без текста исключения: сообщения драйвера могут содержать SQL и адреса.
        logger.error("dictionaries_load_failed", exc_info=True)
        return error_response(500, "INTERNAL_ERROR", "Failed to load dictionaries")
