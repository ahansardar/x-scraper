from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from xingestion.config import AppConfig
from xingestion.protocol_validation import (
    CaptureReplayComparisonReport,
    ProtocolValidationReport,
    build_capture_replay_comparison_report,
    build_protocol_validation_report,
)
from xingestion.releases.manifest_resolver import list_manifest_releases
from xingestion.releases.store import ApprovedReleaseRecord, ReleaseHealth, ReleaseStore
from xingestion.releases.validation_records import (
    RecipeValidationStore,
    record_recipe_validation_results,
)
from xingestion.xprotocol.runtime import validate_recipe_binding
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


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


@dataclass(frozen=True)
class PromotionAuditResult:
    path: Path
    package: dict[str, object]


@dataclass(frozen=True)
class PromotionAuditSummary:
    path: Path
    name: str
    size_bytes: int
    modified_at: str
    package_type: str
    action: str | None
    release_id: str | None
    generated_at: str | None
    approved: bool | None
    forced: bool | None
    safety_ok: bool | None
    readable: bool
    parse_error: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "package_type": self.package_type,
            "action": self.action,
            "release_id": self.release_id,
            "generated_at": self.generated_at,
            "approved": self.approved,
            "forced": self.forced,
            "safety_ok": self.safety_ok,
            "readable": self.readable,
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True)
class PromotionAuditRetentionResult:
    audit_dir: Path
    cutoff: str
    matched_audits: int
    deleted_audits: int
    dry_run: bool
    audits: tuple[PromotionAuditSummary, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "audit_dir": str(self.audit_dir),
            "cutoff": self.cutoff,
            "matched_audits": self.matched_audits,
            "deleted_audits": self.deleted_audits,
            "dry_run": self.dry_run,
            "audits": [item.public_dict() for item in self.audits],
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

    binding_problems: list[str] = []
    for binding in manifest.bindings:
        binding_problems.extend(validate_recipe_binding(binding.recipe))
    checks.append(
        PromotionSafetyCheck(
            name="recipe_binding_consistency",
            ok=not binding_problems,
            severity="HIGH" if binding_problems else "LOW",
            message=(
                "; ".join(binding_problems)
                if binding_problems
                else f"recipe operation/auth_profile/transaction_profile are consistent "
                f"across {len(manifest.bindings)} binding(s)"
            ),
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
    if manifest.bindings:
        record_recipe_validation_results(
            store=RecipeValidationStore(release_store.db_path),
            manifest=manifest,
            capability_id=CapabilityId.SEARCH_TWEETS,
            results=(
                (
                    "FIXTURE",
                    fixture_report.ok,
                    f"{fixture_report.ok_sources}/{fixture_report.checked_sources} fixture sources passed",
                ),
                (
                    "CAPTURE_REPLAY",
                    comparison_ok,
                    (
                        "no comparable capture/replay pairs yet"
                        if comparison.checked_pairs == 0
                        else f"{comparison.ok_pairs}/{comparison.checked_pairs} capture/replay pairs matched"
                    ),
                ),
            ),
        )

    ok = all(check.ok for check in checks)
    return PromotionSafetyReport(
        release_id=release_id,
        ok=ok,
        checks=tuple(checks),
        fixture_validation=fixture_report,
        capture_replay_comparison=comparison,
    )


def write_promotion_audit(
    *,
    config: AppConfig,
    action: str,
    release_id: str,
    manifest_path: Path,
    reason: str,
    safety: PromotionSafetyReport,
    approved: bool,
    forced: bool,
    approval_before: ApprovedReleaseRecord | None,
    approval_after: ApprovedReleaseRecord | None,
    message: str,
    output_path: str | Path | None = None,
) -> PromotionAuditResult:
    package = build_promotion_audit_package(
        action=action,
        release_id=release_id,
        manifest_path=manifest_path,
        reason=reason,
        safety=safety,
        approved=approved,
        forced=forced,
        approval_before=approval_before,
        approval_after=approval_after,
        message=message,
    )
    path = Path(output_path) if output_path else _default_audit_output_path(
        config,
        release_id=release_id,
        action=action,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PromotionAuditResult(path=path, package=package)


def build_promotion_audit_package(
    *,
    action: str,
    release_id: str,
    manifest_path: Path,
    reason: str,
    safety: PromotionSafetyReport,
    approved: bool,
    forced: bool,
    approval_before: ApprovedReleaseRecord | None,
    approval_after: ApprovedReleaseRecord | None,
    message: str,
) -> dict[str, object]:
    return {
        "package_type": "RELEASE_PROMOTION_AUDIT",
        "generated_at": datetime.now(UTC).isoformat(),
        "action": action.strip().upper(),
        "release_id": release_id,
        "manifest_path": str(manifest_path),
        "reason": reason,
        "approved": approved,
        "forced": forced,
        "message": message,
        "approval_before": _approved_release_dict(approval_before),
        "approval_after": _approved_release_dict(approval_after),
        "promotion_safety": safety.public_dict(),
        "redaction": {
            "raw_x_secrets_included": False,
            "raw_evidence_body_included": False,
            "raw_evidence_references_only": True,
        },
    }


def list_promotion_audits(
    config: AppConfig,
    *,
    limit: int = 25,
) -> list[PromotionAuditSummary]:
    audit_dir = promotion_audit_dir(config)
    if not audit_dir.exists():
        return []
    summaries = [_summarize_audit(path) for path in audit_dir.glob("promotion-*.json")]
    summaries.sort(key=lambda item: item.modified_at, reverse=True)
    return summaries[:limit]


def read_promotion_audit(config: AppConfig, name: str) -> dict[str, object]:
    path = promotion_audit_file(config, name)
    summary = _summarize_audit(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "summary": summary.public_dict(),
        "package": payload,
    }


def promotion_audit_file(config: AppConfig, name: str) -> Path:
    path = _promotion_audit_path(config, name)
    if not path.exists():
        raise ValueError(f"Promotion audit {name} not found")
    summary = _summarize_audit(path)
    if not summary.readable:
        raise ValueError(f"Promotion audit {name} is not readable JSON")
    return path


def apply_promotion_audit_retention(
    config: AppConfig,
    *,
    days: int,
    dry_run: bool,
) -> PromotionAuditRetentionResult:
    if days < 1:
        raise ValueError("promotion audit retention days must be at least 1")
    audit_dir = promotion_audit_dir(config)
    cutoff_dt = datetime.now(UTC) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()
    if not audit_dir.exists():
        return PromotionAuditRetentionResult(
            audit_dir=audit_dir,
            cutoff=cutoff,
            matched_audits=0,
            deleted_audits=0,
            dry_run=dry_run,
            audits=(),
        )

    matched: list[PromotionAuditSummary] = []
    deleted = 0
    for path in audit_dir.glob("promotion-*.json"):
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        if modified_at >= cutoff_dt:
            continue
        summary = _summarize_audit(path)
        matched.append(summary)
        if not dry_run:
            path.unlink()
            deleted += 1

    matched.sort(key=lambda item: item.modified_at)
    return PromotionAuditRetentionResult(
        audit_dir=audit_dir,
        cutoff=cutoff,
        matched_audits=len(matched),
        deleted_audits=deleted,
        dry_run=dry_run,
        audits=tuple(matched),
    )


def promotion_audit_dir(config: AppConfig) -> Path:
    return config.data_dir / "release_promotions"


def _default_audit_output_path(config: AppConfig, *, release_id: str, action: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_release_id = _safe_name(release_id)
    safe_action = _safe_name(action.lower())
    return promotion_audit_dir(config) / f"promotion-{safe_release_id}-{safe_action}-{stamp}.json"


def _promotion_audit_path(config: AppConfig, name: str) -> Path:
    if "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError("Promotion audit name must be a file name")
    if not name.startswith("promotion-") or not name.endswith(".json"):
        raise ValueError("Promotion audit name must match promotion-*.json")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(char not in allowed for char in name):
        raise ValueError("Promotion audit name contains unsupported characters")
    return promotion_audit_dir(config) / name


def _summarize_audit(path: Path) -> PromotionAuditSummary:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    base = {
        "path": path,
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return PromotionAuditSummary(
            **base,
            package_type="UNKNOWN",
            action=None,
            release_id=None,
            generated_at=None,
            approved=None,
            forced=None,
            safety_ok=None,
            readable=False,
            parse_error=str(exc),
        )
    if not isinstance(payload, dict):
        return PromotionAuditSummary(
            **base,
            package_type="UNKNOWN",
            action=None,
            release_id=None,
            generated_at=None,
            approved=None,
            forced=None,
            safety_ok=None,
            readable=False,
            parse_error="promotion audit root is not an object",
        )
    safety = payload.get("promotion_safety")
    return PromotionAuditSummary(
        **base,
        package_type=str(payload.get("package_type") or "UNKNOWN"),
        action=payload.get("action") if isinstance(payload.get("action"), str) else None,
        release_id=(
            payload.get("release_id") if isinstance(payload.get("release_id"), str) else None
        ),
        generated_at=(
            payload.get("generated_at") if isinstance(payload.get("generated_at"), str) else None
        ),
        approved=payload.get("approved") if isinstance(payload.get("approved"), bool) else None,
        forced=payload.get("forced") if isinstance(payload.get("forced"), bool) else None,
        safety_ok=(
            safety.get("ok")
            if isinstance(safety, dict) and isinstance(safety.get("ok"), bool)
            else None
        ),
        readable=True,
        parse_error=None,
    )


def _approved_release_dict(
    record: ApprovedReleaseRecord | None,
) -> dict[str, object] | None:
    return record.__dict__ if record is not None else None


def _safe_name(value: str) -> str:
    safe = "".join(char for char in value if char.isalnum() or char in {"-", "_"})
    return safe or "release"
