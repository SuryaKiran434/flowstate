from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings
from sqlalchemy import URL


class Settings(BaseSettings):
    # App
    environment: str = "development"
    secret_key: str = "dev_secret_key_change_in_production"

    # Database
    # Deliberately no connection-string literal here. Writing one out either
    # commits a password to source control or advertises a password-less
    # database, and neither belongs in a repository. Every real deployment path
    # supplies DATABASE_URL from the environment already -- docker-compose.yml,
    # the CI job, and .env all set it -- so the parts below exist only to build
    # a working local URL when it is absent, picking the password up from
    # POSTGRES_PASSWORD rather than from a default baked in here.
    database_url: str = ""
    postgres_user: str = "flowstate"
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "flowstate"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Frontend (used by OAuth callback to redirect back into the SPA)
    frontend_url: str = "http://localhost:3000"

    # Spotify
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:3000/callback"

    # Spotify API URLs
    spotify_auth_url: str = "https://accounts.spotify.com/authorize"
    spotify_token_url: str = "https://accounts.spotify.com/api/token"
    spotify_api_base: str = "https://api.spotify.com/v1"

    # Spotify scopes
    spotify_scopes: str = (
        "user-read-private "
        "user-read-email "
        "user-library-read "
        "playlist-read-private "
        "playlist-read-collaborative "
        "user-top-read "
        "user-follow-read "
        "streaming "
        "user-read-playback-state "
        "user-modify-playback-state"
    )

    # JWT
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Anthropic — used for mood parsing in arc generation
    anthropic_api_key: str = ""

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        """
        Fall back to a URL built from the POSTGRES_* parts when DATABASE_URL is
        unset.

        Built with SQLAlchemy's own URL type rather than an f-string: it escapes
        each component, so a password containing '@' or '/' cannot corrupt the
        URL it lands in, and it keeps this module free of anything shaped like a
        connection string.
        """
        if not self.database_url:
            self.database_url = URL.create(
                drivername="postgresql",
                username=self.postgres_user,
                password=self.postgres_password or None,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
