"""Pytest fixtures shared across unit and integration tests."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest

from tests.utils.runtime_db import PsycopgRuntimeDB


@pytest.fixture(scope="session")
def pg_conn() -> Any:
    """Session-scoped psycopg connection for integration tests."""
    host = os.getenv("TEST_DB_HOST")
    port = os.getenv("TEST_DB_PORT")
    dbname = os.getenv("TEST_DB_NAME")
    user = os.getenv("TEST_DB_USER")
    password = os.getenv("TEST_DB_PASSWORD")

    if not all([host, port, dbname, user, password]):
        pytest.skip("Integration DB env vars are missing; run via ./scripts/test_all.sh")

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def runtime_db(pg_conn: Any) -> PsycopgRuntimeDB:
    """Runtime DB adapter fixture."""
    return PsycopgRuntimeDB(pg_conn)
