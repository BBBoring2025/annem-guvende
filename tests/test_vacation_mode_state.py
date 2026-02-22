"""FIX 7 Tests: Tatil/Away mode state.

- set_system_state + get_system_state calisiyor
- is_vacation_mode() dogru boolean donuyor
"""

import pytest

from src.config import AppConfig
from src.database import (
    get_system_state,
    init_db,
    is_vacation_mode,
    set_system_state,
)


@pytest.fixture
def vacation_db(tmp_path):
    db_path = str(tmp_path / "vacation_test.db")
    init_db(db_path)
    return db_path


def test_get_system_state_default(vacation_db):
    """Olmayan key icin default deger donmeli."""
    val = get_system_state(vacation_db, "nonexistent", "fallback")
    assert val == "fallback"


def test_set_and_get_system_state(vacation_db):
    """set_system_state yazip get_system_state okuyabilmeli."""
    set_system_state(vacation_db, "vacation_mode", "true")
    val = get_system_state(vacation_db, "vacation_mode")
    assert val == "true"


def test_set_system_state_overwrites(vacation_db):
    """set_system_state mevcut degeri guncelleyebilmeli."""
    set_system_state(vacation_db, "vacation_mode", "true")
    set_system_state(vacation_db, "vacation_mode", "false")
    val = get_system_state(vacation_db, "vacation_mode")
    assert val == "false"


def test_is_vacation_mode_true_from_db(vacation_db):
    """DB'de vacation_mode=true iken is_vacation_mode True donmeli."""
    set_system_state(vacation_db, "vacation_mode", "true")
    config = AppConfig(system={"vacation_mode": False})  # config false, DB true -> True
    assert is_vacation_mode(vacation_db, config) is True


def test_is_vacation_mode_false_from_db(vacation_db):
    """DB'de vacation_mode=false iken is_vacation_mode False donmeli."""
    set_system_state(vacation_db, "vacation_mode", "false")
    config = AppConfig(system={"vacation_mode": True})  # config true, DB false -> False
    assert is_vacation_mode(vacation_db, config) is False


def test_is_vacation_mode_fallback_to_config(vacation_db):
    """DB'de state yoksa config'e dusmeli."""
    config = AppConfig(system={"vacation_mode": True})
    assert is_vacation_mode(vacation_db, config) is True


def test_is_vacation_mode_default_false(vacation_db):
    """DB'de state yok, config'te de yok -> False."""
    config = AppConfig()
    assert is_vacation_mode(vacation_db, config) is False
