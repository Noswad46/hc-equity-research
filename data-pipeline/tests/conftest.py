"""Shared fixture loading.

`data-pipeline` has a hyphen in its name, so it cannot be imported as a package.
`pytest.ini` puts it on `sys.path` instead, which makes `sources.edgar` and
`transform.fundamentals` importable from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PIPELINE_ROOT = Path(__file__).resolve().parent.parent


def load_fixture(name: str) -> dict[str, Any]:
    """Read one `companyfacts` fixture by stem."""
    path = FIXTURES / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no fixture {name!r} in {FIXTURES}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def pipeline_root() -> Path:
    return PIPELINE_ROOT


@pytest.fixture(scope="session")
def universe_path(pipeline_root: Path) -> Path:
    return pipeline_root / "universe.yaml"


# Real, trimmed `companyfacts` payloads. Each is session-scoped and must be
# treated as read-only by tests.
@pytest.fixture(scope="session")
def pfe() -> dict[str, Any]:
    return load_fixture("pfe_companyfacts")


@pytest.fixture(scope="session")
def mrna() -> dict[str, Any]:
    return load_fixture("mrna_companyfacts")


@pytest.fixture(scope="session")
def bdx() -> dict[str, Any]:
    return load_fixture("bdx_companyfacts")


@pytest.fixture(scope="session")
def mrk() -> dict[str, Any]:
    return load_fixture("mrk_companyfacts")


@pytest.fixture(scope="session")
def bntx() -> dict[str, Any]:
    return load_fixture("bntx_companyfacts")


# Hand-built payloads with round numbers, so the arithmetic can be checked by eye.
@pytest.fixture(scope="session")
def ytd_only() -> dict[str, Any]:
    return load_fixture("synthetic_ytd_only")


@pytest.fixture(scope="session")
def restated() -> dict[str, Any]:
    return load_fixture("synthetic_restated")


@pytest.fixture(scope="session")
def fallback_chain() -> dict[str, Any]:
    return load_fixture("synthetic_fallback_chain")
