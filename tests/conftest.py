import os

import pytest


# Пропущенный тест при FAIL_ON_SKIP=1 считается ошибкой: иначе недошедшие до
# контейнера TEST_DB_* молча отключили бы все интеграционные тесты.
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if os.getenv("FAIL_ON_SKIP") == "1" and report.skipped:
        report.outcome = "failed"
        report.longrepr = (
            f"Skipped test is not allowed with FAIL_ON_SKIP=1: {item.nodeid}"
        )
