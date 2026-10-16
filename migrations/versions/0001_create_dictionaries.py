"""Create dictionary tables and seed fixed values (SMAI-86)

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Значения заморожены в ревизии: LE-7…LE-10 (SMAI-A-233…236) и API-7 (SMAI-A-224).
# Изменение справочника — новой ревизией, id существующих значений не меняются.
SEEDS: dict[str, list[tuple[int, str]]] = {
    "habit": [
        (1, "Быстрые перекусы"),
        (2, "Низкокалорийные блюда"),
        (3, "Полезная еда"),
        (4, "Еда с собой"),
        (5, "Высокобелковая"),
        (6, "Для семейных приёмов пищи"),
    ],
    "diet": [
        (1, "Веган"),
        (2, "Вегетарианец"),
        (3, "Кето"),
        (4, "Средиземноморская"),
    ],
    "allergen": [
        (1, "Глютен"),
        (2, "Лактоза"),
        (3, "Яйца"),
        (4, "Арахис"),
        (5, "Древесные орехи"),
        (6, "Соя"),
        (7, "Рыба"),
        (8, "Ракообразные"),
        (9, "Моллюски"),
        (10, "Кунжут"),
        (11, "Горчица"),
        (12, "Сельдерей"),
        (13, "Люпин"),
        (14, "Сульфиты"),
        (15, "Пшеница"),
        (16, "Кукуруза"),
        (17, "Мёд"),
        (18, "Цитрусовые"),
        (19, "Какао / шоколад"),
        (20, "Клубника"),
    ],
    "kitchen_tool": [
        (1, "Плита"),
        (2, "Духовка"),
        (3, "Микроволновая печь"),
        (4, "Аэрогриль"),
        (5, "Мультиварка"),
        (6, "Блендер"),
        (7, "Тостер"),
        (8, "Пароварка"),
        (9, "Электрический гриль"),
        (10, "Фритюрница"),
        (11, "Миксер"),
        (12, "Су-вид"),
        (13, "Вафельница"),
        (14, "Хлебопечка"),
        (15, "Кофемашина"),
    ],
}


def upgrade() -> None:
    for table, rows in SEEDS.items():
        created = op.create_table(
            table,
            # id задаются только сидами: без identity/serial.
            sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            sa.UniqueConstraint("name", name=f"uq_{table}_name"),
        )
        op.bulk_insert(created, [{"id": row_id, "name": name} for row_id, name in rows])


def downgrade() -> None:
    for table in reversed(SEEDS):
        op.drop_table(table)
