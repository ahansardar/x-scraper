from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from xingestion.sessions.network import parse_network_policy
from xingestion.sessions.store import SessionHealth, SessionRecord, SessionStore


@dataclass(frozen=True)
class SessionRegistryEntry:
    session_id: str
    account_label: str
    credential_ref: str
    network_context: str
    health: SessionHealth = SessionHealth.HEALTHY

    def public_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "account_label": self.account_label,
            "reference_configured": bool(self.credential_ref),
            "reference_scheme": _reference_scheme(self.credential_ref),
            "network_context": self.network_context,
            "network_policy": parse_network_policy(self.network_context).public_dict(),
            "health": self.health.value,
        }


@dataclass(frozen=True)
class SessionRegistryImportResult:
    source: str
    imported: int
    sessions: tuple[SessionRecord, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "imported": self.imported,
            "sessions": [
                {
                    "session_id": session.session_id,
                    "account_label": session.account_label,
                    "reference_configured": bool(session.credential_ref),
                    "reference_scheme": _reference_scheme(session.credential_ref),
                    "network_context": session.network_context,
                    "network_policy": session.network_policy.public_dict(),
                    "health": session.health.value,
                }
                for session in self.sessions
            ],
        }


def load_session_registry(path: Path) -> tuple[SessionRegistryEntry, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        raise ValueError("session registry must contain a sessions array")
    return tuple(_entry_from_dict(item) for item in payload["sessions"])


def import_session_registry(
    *,
    store: SessionStore,
    path: Path,
) -> SessionRegistryImportResult:
    entries = load_session_registry(path)
    imported = tuple(
        store.upsert_session(
            session_id=entry.session_id,
            account_label=entry.account_label,
            credential_ref=entry.credential_ref,
            network_context=entry.network_context,
            health=entry.health,
        )
        for entry in entries
    )
    return SessionRegistryImportResult(
        source=str(path),
        imported=len(imported),
        sessions=imported,
    )


def _entry_from_dict(payload: object) -> SessionRegistryEntry:
    if not isinstance(payload, dict):
        raise ValueError("session registry entries must be objects")
    session_id = str(payload.get("session_id") or "").strip()
    account_label = str(payload.get("account_label") or "").strip()
    credential_ref = str(payload.get("credential_ref") or "").strip()
    network_context = parse_network_policy(str(payload.get("network_context") or "direct")).label
    health = SessionHealth(str(payload.get("health") or SessionHealth.HEALTHY.value))
    if not session_id:
        raise ValueError("session_id cannot be empty")
    if not account_label:
        raise ValueError("account_label cannot be empty")
    if not credential_ref:
        raise ValueError("credential_ref cannot be empty")
    return SessionRegistryEntry(
        session_id=session_id,
        account_label=account_label,
        credential_ref=credential_ref,
        network_context=network_context or "direct",
        health=health,
    )


def _reference_scheme(credential_ref: str) -> str:
    if ":" not in credential_ref:
        return "unknown"
    return credential_ref.split(":", 1)[0]
