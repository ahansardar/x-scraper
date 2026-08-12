from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xingestion.releases.store import ReleaseHealth, ReleaseStore
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


@dataclass(frozen=True)
class ResolvedProtocolRelease:
    release_id: str
    manifest_path: Path
    manifest: ProtocolReleaseManifest


@dataclass(frozen=True)
class ManifestReleaseCandidate:
    release_id: str
    manifest_path: Path
    manifest_status: str
    binding_count: int
    capabilities: tuple[str, ...]
    recipe_revision_ids: tuple[str, ...]
    approved: bool
    approval_reason: str | None
    approval_updated_at: str | None
    health: ReleaseHealth
    health_reason: str
    health_updated_at: str

    def public_dict(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "manifest_path": str(self.manifest_path),
            "manifest_status": self.manifest_status,
            "binding_count": self.binding_count,
            "capabilities": list(self.capabilities),
            "recipe_revision_ids": list(self.recipe_revision_ids),
            "approved": self.approved,
            "approval_reason": self.approval_reason,
            "approval_updated_at": self.approval_updated_at,
            "health": self.health.value,
            "health_reason": self.health_reason,
            "health_updated_at": self.health_updated_at,
            "execution_allowed": self.health not in {
                ReleaseHealth.QUARANTINED,
                ReleaseHealth.RETIRED,
            },
        }


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


def list_manifest_releases(
    *,
    release_store: ReleaseStore,
    manifest_dir: Path,
) -> tuple[ManifestReleaseCandidate, ...]:
    manifests = _load_manifests(manifest_dir)
    approval = release_store.approved_release()
    candidates = []
    for candidate in manifests:
        manifest = candidate.manifest
        health = release_store.ensure_release(manifest.release_id)
        approved = approval is not None and approval.release_id == manifest.release_id
        candidates.append(
            ManifestReleaseCandidate(
                release_id=manifest.release_id,
                manifest_path=candidate.manifest_path,
                manifest_status=manifest.status.value,
                binding_count=len(manifest.bindings),
                capabilities=tuple(
                    binding.capability_id.value for binding in manifest.bindings
                ),
                recipe_revision_ids=tuple(
                    binding.recipe.revision_id for binding in manifest.bindings
                ),
                approved=approved,
                approval_reason=approval.reason if approved and approval else None,
                approval_updated_at=approval.updated_at if approved and approval else None,
                health=health.health,
                health_reason=health.reason,
                health_updated_at=health.updated_at,
            )
        )
    return tuple(candidates)


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
