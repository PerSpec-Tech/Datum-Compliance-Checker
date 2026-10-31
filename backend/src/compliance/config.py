from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    tavily_api_key: str = ""

    app_db_path: Path = REPO_ROOT / "data" / "app.sqlite"
    app_public_url: str = "http://localhost:8000"
    app_secret: str = "change-me"
    # Threads for reading IFC geometry. Each one holds geometry in memory, and in a container
    # the CPU count is the host's, not the container's, so this is a fixed number.
    geom_threads: int = 2
    head_html: str = ""  # optional markup added to the web page's <head> by this deployment
    nominatim_user_agent: str = (
        "PERSPEC-ComplianceChecker/0.1 (hackathon demo; Revit bylaw checker)"
    )

    models_file: Path = BACKEND_ROOT / "config" / "models.yaml"
    rules_dir: Path = REPO_ROOT / "rules"
    schemas_dir: Path = REPO_ROOT / "schemas"
    cache_dir: Path = REPO_ROOT / ".cache"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Relative paths in .env are relative to the repo, not to the folder the server started in.
    for field in ("app_db_path", "cache_dir"):
        path = getattr(s, field)
        if not path.is_absolute():
            setattr(s, field, (REPO_ROOT / path).resolve())
    return s
