"""Database fixtures: every test run gets a brand new database, migrated
from scratch, and drops it at the end."""

import os
import uuid

import psycopg
import pytest

from server.db.migrate import apply_migrations


def _admin_url() -> str:
    admin_url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set: run with docker compose run --rm tests")
    return admin_url


def _url_for_database(admin_url: str, database_name: str) -> str:
    # The admin URL ends with "/postgres"; swap the database name.
    return admin_url.rsplit("/", 1)[0] + "/" + database_name


@pytest.fixture(scope="session")
def database_url():
    admin_url = _admin_url()
    database_name = f"game_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database_name}"')
    test_url = _url_for_database(admin_url, database_name)
    with psycopg.connect(test_url, autocommit=True) as conn:
        apply_migrations(conn)
    yield test_url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn
