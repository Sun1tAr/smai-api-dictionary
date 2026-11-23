import pytest
from spec_data import TABLES
from sqlalchemy import Integer, String, UniqueConstraint


def test_there_are_exactly_the_four_dictionary_tables() -> None:
    from dictionary import models  # noqa: F401
    from dictionary.database import Base

    assert set(Base.metadata.tables) == set(TABLES)


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_table_has_stable_integer_pk_and_unique_name(table_name: str) -> None:
    from dictionary import models  # noqa: F401
    from dictionary.database import Base

    table = Base.metadata.tables[table_name]
    assert [column.name for column in table.columns] == ["id", "name"]
    assert [column.name for column in table.primary_key.columns] == ["id"]
    assert isinstance(table.c.id.type, Integer)
    # id задаются только сидами: без identity/serial.
    assert table.c.id.autoincrement is False
    assert table.c.id.identity is None and table.c.id.server_default is None
    assert isinstance(table.c.name.type, String)
    assert table.c.name.nullable is False
    unique = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert [[column.name for column in c.columns] for c in unique] == [["name"]]
    assert unique[0].name == f"uq_{table_name}_name"
    assert table.primary_key.name == f"pk_{table_name}"
