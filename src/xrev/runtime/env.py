from __future__ import annotations

import os
from pathlib import Path

from .search_tweets import WebSessionAuth


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def web_session_auth_from_env() -> WebSessionAuth:
    return WebSessionAuth(
        auth_token=os.getenv("X_AUTH_TOKEN", ""),
        ct0=os.getenv("X_CT0", ""),
        bearer_token=os.getenv("X_BEARER", ""),
    )
