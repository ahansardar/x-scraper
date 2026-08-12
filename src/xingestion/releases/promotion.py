from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xingestion.protocol_validation import (
    CaptureReplayComparisonReport,
    ProtocolValidationReport,
    build_capture_replay_comparison_report,
    build_protocol_validation_report,
)
from xingestion.releases.manifest_resolver import list_manifest_releases
from xingestion.releases.store import ReleaseHealth, ReleaseStore
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


@dataclass(frozen=True)
class PromotionSafetyCheck:
    name: str
    ok: bool
    severity: str
    message: str

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class PromotionSafetyReport:
    release_id: str
    ok: bool
    checks: tuple[PromotionSafetyCheck, ...]
    fixture_validation: ProtocolValidationReport
    capture_replay_comparison: CaptureReplayComparisonReport

    def public_dict(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "ok": self.ok,
            "checks": [check.public_dict() for check in self.checks],
            "fixture_validation": self.fixture_validation.public_dict(),
            "capture_replay_comparison": self.capture_replay_comparison.public_dict(),
        }


def build_promotion_safety_report(
    *,
    release_id: str,
    manifest: ProtocolReleaseManifest,
    release_store: ReleaseStore,
    manifest_dir: Path,
    raw_evidence_dir: Path,
) -> PromotionSafetyReport:
    checks = []
    candidates = {
        candidate.release_id: candidate
        for candidate in list_manifest_releases(
            release_store=release_store,
            manifest_dir=manifest_dir,
        )
    }
    candidate = candidates.get(release_id)
    checks.append(
        PromotionSafetyCheck(
            name="manifest_present",
            ok=candidate is not None,
            severity="HIGH" if candidate is None else "LOW",
            message=(
                f"manifest found at {candidate.manifest_path}"
                if candidate is not None
                else f"no manifest found for release {release_id}"
            ),
        )
    )
    checks.append(
        PromotionSafetyCheck(
            name="manifest_release_match",
            ok=manifest.release_id == release_id,
            severity="HIGH" if manifest.release_id != release_id else "LOW",
            message=f"manifest release_id={manifest.release_id}",
        )
    )
    release = release_store.ensure_release(release_id)
    blocked_health = release.health in {ReleaseHealth.QUARANTINED, ReleaseHealth.RETIRED}
    checks.append(
        PromotionSafetyCheck(
            name="release_health_allows_execution",
            ok=not blocked_health,
            severity="HIGH" if blocked_health else "LOW",
            message=f"release health={release.health.value} reason={release.reason}",
        )
    )
    checks.append(
        PromotionSafetyCheck(
            name="bindings_present",
            ok=bool(manifest.bindings),
            severity="HIGH" if not manifest.bindings else "LOW",
            message=f"bindings={len(manifest.bindings)}",
        )
    )

    parser_revision_id = (
        manifest.bindings[0].recipe.parser.revision_id if manifest.bindings else "unknown"
    )
    fixture_report = build_protocol_validation_report(
        raw_evidence_dir=None,
        parser_revision_id=parser_revision_id,
        include_fixtures=True,
    )
    checks.append(
        PromotionSafetyCheck(
            name="fixture_validation",
            ok=fixture_report.ok,
            severity="HIGH" if not fixture_report.ok else "LOW",
            message=(
                f"{fixture_report.ok_sources}/{fixture_report.checked_sources} fixture sources passed"
            ),
        )
    )

    comparison = build_capture_replay_comparison_report(
        raw_evidence_dir=raw_evidence_dir,
        limit=10,
    )
    comparison_ok = comparison.ok or comparison.checked_pairs == 0
    checks.append(
        PromotionSafetyCheck(
            name="capture_replay_comparison",
            ok=comparison_ok,
            severity="HIGH" if not comparison_ok else "LOW",
            message=(
                "no comparable capture/replay pairs yet"
                if comparison.checked_pairs == 0
                else f"{comparison.ok_pairs}/{comparison.checked_pairs} capture/replay pairs matched"
            ),
        )
    )
    ok = all(check.ok for check in checks)
    return PromotionSafetyReport(
        release_id=release_id,
        ok=ok,
        checks=tuple(checks),
        fixture_validation=fixture_report,
        capture_replay_comparison=comparison,
    )
