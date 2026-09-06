from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).with_name("sample_server.py")


@pytest.fixture(scope="session")
def server_cmd() -> str:
    """Shell command that launches the sample server over stdio."""
    return f'"{sys.executable}" "{SERVER}"'
