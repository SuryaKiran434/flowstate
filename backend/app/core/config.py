from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    environment: str = "development"
    secret_key: str = "dev_secret_key_change_in_production"

    # Database
    database_url: str = "postgresql://flowstate:flowstate_dev@db:5432/flowstate"

    # Redis
    redis_url: str = "redis://redis:6379/0"

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

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
