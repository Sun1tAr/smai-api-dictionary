from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DictionaryItem(BaseModel):
    id: int = Field(
        description="Стабильный идентификатор значения, уникальный внутри справочника.",
        examples=[1],
    )
    name: str = Field(
        description="Название значения, уникальное внутри справочника.",
        examples=["Веган"],
    )


def items(*names: str) -> list[dict[str, Any]]:
    return [{"id": index, "name": name} for index, name in enumerate(names, start=1)]


# Пример совпадает с API-7 (SMAI-A-224); сверяется с сидами тестом.
RESPONSE_EXAMPLE: dict[str, Any] = {
    "habits": items(
        "Быстрые перекусы",
        "Низкокалорийные блюда",
        "Полезная еда",
        "Еда с собой",
        "Высокобелковая",
        "Для семейных приёмов пищи",
    ),
    "diets": items("Веган", "Вегетарианец", "Кето", "Средиземноморская"),
    "allergies": items(
        "Глютен",
        "Лактоза",
        "Яйца",
        "Арахис",
        "Древесные орехи",
        "Соя",
        "Рыба",
        "Ракообразные",
        "Моллюски",
        "Кунжут",
        "Горчица",
        "Сельдерей",
        "Люпин",
        "Сульфиты",
        "Пшеница",
        "Кукуруза",
        "Мёд",
        "Цитрусовые",
        "Какао / шоколад",
        "Клубника",
    ),
    "kitchenTools": items(
        "Плита",
        "Духовка",
        "Микроволновая печь",
        "Аэрогриль",
        "Мультиварка",
        "Блендер",
        "Тостер",
        "Пароварка",
        "Электрический гриль",
        "Фритюрница",
        "Миксер",
        "Су-вид",
        "Вафельница",
        "Хлебопечка",
        "Кофемашина",
    ),
}


class DictionariesResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, json_schema_extra={"example": RESPONSE_EXAMPLE}
    )

    habits: list[DictionaryItem] = Field(
        description="Справочник пищевых привычек (LE-7)."
    )
    diets: list[DictionaryItem] = Field(description="Справочник диет (LE-8).")
    allergies: list[DictionaryItem] = Field(description="Справочник аллергенов (LE-9).")
    kitchen_tools: list[DictionaryItem] = Field(
        alias="kitchenTools", description="Справочник кухонной техники (LE-10)."
    )
