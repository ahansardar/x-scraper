from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xingestion.releases.store import ReleaseStore
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


@dataclass(frozen=True)
class ResolvedProtocolRelease:
    release_id: str
    manifest_path: Path
    manifest: ProtocolReleaseManifest


def resolve_approved_manifest(
    *,
    release_store: ReleaseStore,
    manifest_dir: Path,
) -> ResolvedProtocolRelease:
    manifests = _load_manifests(manifest_dir)
    approved_release_id = release_store.approved_release_id()
    if approved_release_id is None:
        if len(manifests) != 1:
            raise ValueError(
                "No approved protocol release is configured and manifest repository "
                f"contains {len(manifests)} manifests"
            )
        approved_release_id = manifests[0].manifest.release_id
        release_store.approve_release(
            approved_release_id,
            reason="bootstrap_single_manifest_repository",
        )

    matches = [
        candidate
        for candidate in manifests
        if candidate.manifest.release_id == approved_release_id
    ]
    if not matches:
        raise ValueError(
            f"Approved protocol release {approved_release_id} has no matching manifest"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Approved protocol release {approved_release_id} has multiple matching manifests"
        )

    release_store.ensure_release(matches[0].manifest.release_id)
    return matches[0]


def _load_manifests(manifest_dir: Path) -> tuple[ResolvedProtocolRelease, ...]:
    if not manifest_dir.exists():
        raise ValueError(f"Protocol manifest directory does not exist: {manifest_dir}")
    manifests = []
    for path in sorted(manifest_dir.glob("*.json")):
        manifest = ProtocolReleaseManifest.from_file(path)
        manifests.append(
            ResolvedProtocolRelease(
                release_id=manifest.release_id,
                manifest_path=path,
                manifest=manifest,
            )
        )
    if not manifests:
        raise ValueError(f"No protocol manifests found in {manifest_dir}")
    return tuple(manifests)
