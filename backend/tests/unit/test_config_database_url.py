"""
Unit tests for the DATABASE_URL fallback in Settings.

The fallback exists so a local run works without DATABASE_URL set, and it is
built with SQLAlchemy's URL type rather than an f-string precisely so that a
password containing URL-significant characters cannot corrupt the DSN it lands
in. These tests pin both halves of that.

Covers:
- DATABASE_URL, when supplied, is used verbatim and no fallback runs
- absent DATABASE_URL assembles a DSN from the POSTGRES_* parts
- '@' and '/' in the password are escaped rather than splitting the authority
- an empty password produces a DSN with no password section
- a non-default host/port/database reach the assembled DSN
"""

import pytest
from sqlalchemy import make_url

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch):
    """Ignore any DATABASE_URL/POSTGRES_* inherited from the developer's shell."""
    for var in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(var, raising=False)


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


class TestExplicitUrl:
    def test_supplied_url_is_used_verbatim(self):
        s = _settings(database_url="postgresql://someone:pw@db.example:6543/app")
        assert s.database_url == "postgresql://someone:pw@db.example:6543/app"

    def test_supplied_url_ignores_the_postgres_parts(self):
        s = _settings(
            database_url="postgresql://someone:pw@db.example/app",
            postgres_host="should-not-appear",
        )
        assert "should-not-appear" not in s.database_url


class TestAssembledFallback:
    def test_parts_are_assembled_when_url_is_absent(self):
        s = _settings(
            postgres_user="flow",
            postgres_password="secret",
            postgres_host="pg",
            postgres_port=5433,
            postgres_db="flowdb",
        )
        url = make_url(s.database_url)
        assert url.drivername == "postgresql"
        assert url.username == "flow"
        assert url.password == "secret"
        assert url.host == "pg"
        assert url.port == 5433
        assert url.database == "flowdb"

    def test_password_with_at_sign_does_not_split_the_authority(self):
        s = _settings(postgres_password="p@ss", postgres_host="pg")
        url = make_url(s.database_url)
        # The naive f-string version would have parsed "ss@pg" as the host.
        assert url.host == "pg"
        assert url.password == "p@ss"
        assert "%40" in s.database_url

    def test_password_with_slash_does_not_start_the_database_path(self):
        s = _settings(postgres_password="a/b", postgres_db="flowdb")
        url = make_url(s.database_url)
        assert url.database == "flowdb"
        assert url.password == "a/b"

    @pytest.mark.parametrize("password", ["p@ss/w:rd?x#y", "'; DROP--", "üñí"])
    def test_hostile_passwords_round_trip(self, password):
        s = _settings(postgres_password=password, postgres_host="pg", postgres_db="d")
        url = make_url(s.database_url)
        assert url.password == password
        assert url.host == "pg"
        assert url.database == "d"

    def test_empty_password_produces_no_password_section(self):
        s = _settings(postgres_password="", postgres_user="flow", postgres_host="pg")
        assert make_url(s.database_url).password is None
        assert "flow@pg" in s.database_url
