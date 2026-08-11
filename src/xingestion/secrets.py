from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from xingestion.config import AppConfig
from xrev.runtime import WebSessionAuth


@dataclass(frozen=True)
class SecretProviderStatus:
    provider: str
    configured: bool
    reference_scheme: str
    reference_configured: bool
    missing_fields: tuple[str, ...]
    message: str

    def public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "reference_scheme": self.reference_scheme,
            "reference_configured": self.reference_configured,
            "missing_fields": list(self.missing_fields),
            "message": self.message,
        }


class SecretProvider:
    provider_name = "unknown"

    def resolve_web_session_auth(self, credential_ref: str) -> WebSessionAuth:
        raise NotImplementedError

    def status(self, credential_ref: str) -> SecretProviderStatus:
        try:
            auth = self.resolve_web_session_auth(credential_ref)
            missing = auth.missing_fields()
            configured = not missing
            message = "web session auth resolved" if configured else "web session auth incomplete"
        except ValueError as exc:
            missing = ()
            configured = False
            message = str(exc)
        return SecretProviderStatus(
            provider=self.provider_name,
            configured=configured,
            reference_scheme=_reference_scheme(credential_ref),
            reference_configured=bool(credential_ref),
            missing_fields=missing,
            message=message,
        )


class EnvSecretProvider(SecretProvider):
    provider_name = "env"

    def resolve_web_session_auth(self, credential_ref: str) -> WebSessionAuth:
        keys = _env_keys_from_ref(credential_ref)
        return WebSessionAuth(
            auth_token=os.getenv(keys[0], ""),
            ct0=os.getenv(keys[1], ""),
            bearer_token=os.getenv(keys[2], ""),
        )


class FileSecretProvider(SecretProvider):
    provider_name = "file"

    def __init__(self, secret_dir: Path) -> None:
        self.secret_dir = secret_dir

    def resolve_web_session_auth(self, credential_ref: str) -> WebSessionAuth:
        if not credential_ref.startswith("file:"):
            raise ValueError("file provider requires credential_ref starting with file:")
        name = credential_ref.removeprefix("file:").strip()
        path = _safe_secret_file(self.secret_dir, name)
        if not path.exists():
            raise ValueError(f"secret file not found for credential_ref {credential_ref}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("secret file must contain a JSON object")
        return WebSessionAuth(
            auth_token=str(payload.get("auth_token") or ""),
            ct0=str(payload.get("ct0") or ""),
            bearer_token=str(payload.get("bearer_token") or ""),
        )


def build_secret_provider(config: AppConfig) -> SecretProvider:
    if config.secret_provider == "env":
        return EnvSecretProvider()
    if config.secret_provider == "file":
        return FileSecretProvider(config.secret_dir)
    raise ValueError(f"Unsupported XINGESTION_SECRET_PROVIDER {config.secret_provider}")


def resolve_web_session_auth(config: AppConfig) -> WebSessionAuth:
    return build_secret_provider(config).resolve_web_session_auth(
        config.default_credential_ref
    )


def secret_provider_status(config: AppConfig) -> SecretProviderStatus:
    return build_secret_provider(config).status(config.default_credential_ref)


def _env_keys_from_ref(credential_ref: str) -> tuple[str, str, str]:
    if not credential_ref.startswith("env:"):
        raise ValueError("env provider requires credential_ref starting with env:")
    keys = tuple(part.strip() for part in credential_ref.removeprefix("env:").split(","))
    if len(keys) != 3 or any(not key for key in keys):
        raise ValueError("env credential_ref must name auth_token, ct0, and bearer env keys")
    return keys


def _safe_secret_file(secret_dir: Path, name: str) -> Path:
    if not name or any(separator in name for separator in ("/", "\\")) or ".." in name:
        raise ValueError("file credential_ref must be a simple secret name")
    return secret_dir / f"{name}.json"


def _reference_scheme(credential_ref: str) -> str:
    if ":" not in credential_ref:
        return "unknown"
    return credential_ref.split(":", 1)[0]
