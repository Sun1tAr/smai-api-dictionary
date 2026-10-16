from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from dictionary.database import Base


# Справочники фиксированы: id задаются сидами миграций (без identity/serial) и
# остаются стабильными, name уникально внутри справочника.
class DictionaryEntry:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Habit(DictionaryEntry, Base):
    __tablename__ = "habit"


class Diet(DictionaryEntry, Base):
    __tablename__ = "diet"


class Allergen(DictionaryEntry, Base):
    __tablename__ = "allergen"


class KitchenTool(DictionaryEntry, Base):
    __tablename__ = "kitchen_tool"
