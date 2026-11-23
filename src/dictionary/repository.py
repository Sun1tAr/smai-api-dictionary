from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dictionary.models import Allergen, Diet, Habit, KitchenTool
from dictionary.schemas import DictionariesResponse, DictionaryItem


async def _load(session: AsyncSession, model: type) -> list[DictionaryItem]:
    rows = await session.execute(select(model.id, model.name).order_by(model.id))
    return [DictionaryItem(id=row.id, name=row.name) for row in rows]


# Одна READ ONLY-транзакция с моментальным снимком: все четыре справочника
# читаются согласованно, даже если миграция меняет данные во время запроса.
async def load_dictionaries(
    session_factory: async_sessionmaker[AsyncSession],
) -> DictionariesResponse:
    async with session_factory() as session:
        await session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        return DictionariesResponse(
            habits=await _load(session, Habit),
            diets=await _load(session, Diet),
            allergies=await _load(session, Allergen),
            kitchen_tools=await _load(session, KitchenTool),
        )
