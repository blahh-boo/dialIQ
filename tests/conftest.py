"""Shared pytest fixtures.

Sets default env vars so `maple.config.Settings` validates without a real
.env present during unit-test runs. Integration tests that need a live DB / API
should explicitly override these.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _default_env() -> None:
    os.environ.setdefault("RUN_MODE", "mock")
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
