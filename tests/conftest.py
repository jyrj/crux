"""Shared fixtures for crux tests."""

from pathlib import Path

import pytest

DESIGNS_DIR = Path(__file__).parent / "designs"


@pytest.fixture
def designs_dir():
    return DESIGNS_DIR
