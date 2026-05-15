"""Smoke tests: package imports and settings load."""

from __future__ import annotations

import mystery_shop
from mystery_shop.config import RunMode, Settings


def test_package_has_version() -> None:
    assert isinstance(mystery_shop.__version__, str)
    assert mystery_shop.__version__


def test_settings_load_with_defaults() -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.run_mode is RunMode.MOCK
    assert settings.database_url.startswith("postgresql+psycopg://")
