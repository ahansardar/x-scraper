from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class RawEvidenceRef:
    evidence_id: str
    content_sha256: str
    media_type: str
    storage_uri: str
    captured_at: str
    metadata: Mapping[str, str]


class RawEvidenceSink(Protocol):
    def store_json(
        self,
        payload: Mapping[str, Any],
        *,
        media_type: str = "application/json",
        metadata: Mapping[str, str] | None = None,
    ) -> RawEvidenceRef:
        """Persist a raw protocol response and return a stable reference."""


class FileRawEvidenceSink:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def store_json(
        self,
        payload: Mapping[str, Any],
        *,
        media_type: str = "application/json",
        metadata: Mapping[str, str] | None = None,
    ) -> RawEvidenceRef:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        content_hash = hashlib.sha256(encoded).hexdigest()
        evidence_id = f"raw-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:12]}"

        self.root.mkdir(parents=True, exist_ok=True)
        json_path = self.root / f"{evidence_id}.json"
        meta_path = self.root / f"{evidence_id}.metadata.json"

        json_path.write_bytes(encoded)

        captured_at = datetime.now(UTC).isoformat()
        safe_metadata = dict(metadata or {})
        ref = RawEvidenceRef(
            evidence_id=evidence_id,
            content_sha256=content_hash,
            media_type=media_type,
            storage_uri=str(json_path),
            captured_at=captured_at,
            metadata=safe_metadata,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "evidence_id": ref.evidence_id,
                    "content_sha256": ref.content_sha256,
                    "media_type": ref.media_type,
                    "storage_uri": ref.storage_uri,
                    "captured_at": ref.captured_at,
                    "metadata": ref.metadata,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return ref
