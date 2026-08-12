from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.releases import (
    ReleaseStore,
    apply_promotion_audit_retention,
    build_promotion_safety_report,
    list_manifest_releases,
    list_promotion_audits,
    read_promotion_audit,
    resolve_approved_manifest,
    write_promotion_audit,
)
from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="releases", console=False)
    store = ReleaseStore(config.sqlite_path)
    manifest_dir = ROOT / "protocol_releases"

    if args.command == "current":
        resolved = resolve_approved_manifest(
            release_store=store,
            manifest_dir=manifest_dir,
        )
        payload = {
            "release_id": resolved.release_id,
            "manifest_path": str(resolved.manifest_path),
            "approved_release": (
                store.approved_release().__dict__
                if store.approved_release() is not None
                else None
            ),
        }
        return _print(payload, json_output=args.json)

    if args.command == "check":
        candidates = {
            candidate.release_id: candidate
            for candidate in list_manifest_releases(
                release_store=store,
                manifest_dir=manifest_dir,
            )
        }
        if args.release_id not in candidates:
            raise SystemExit(f"Release manifest not found: {args.release_id}")
        manifest = ProtocolReleaseManifest.from_file(
            candidates[args.release_id].manifest_path
        )
        report = build_promotion_safety_report(
            release_id=args.release_id,
            manifest=manifest,
            release_store=store,
            manifest_dir=manifest_dir,
            raw_evidence_dir=config.raw_evidence_dir,
        )
        audit = write_promotion_audit(
            config=config,
            action="CHECK",
            release_id=args.release_id,
            manifest_path=candidates[args.release_id].manifest_path,
            reason="operator_check",
            safety=report,
            approved=False,
            forced=False,
            approval_before=store.approved_release(),
            approval_after=store.approved_release(),
            message="Promotion safety checked",
        )
        payload = report.public_dict()
        payload["audit_path"] = str(audit.path)
        return _print(payload, json_output=args.json)

    if args.command == "approve":
        candidates = {
            candidate.release_id: candidate
            for candidate in list_manifest_releases(
                release_store=store,
                manifest_dir=manifest_dir,
            )
        }
        if args.release_id not in candidates:
            raise SystemExit(f"Release manifest not found: {args.release_id}")
        manifest = ProtocolReleaseManifest.from_file(
            candidates[args.release_id].manifest_path
        )
        safety = build_promotion_safety_report(
            release_id=args.release_id,
            manifest=manifest,
            release_store=store,
            manifest_dir=manifest_dir,
            raw_evidence_dir=config.raw_evidence_dir,
        )
        approval_before = store.approved_release()
        if not safety.ok and not args.force:
            audit = write_promotion_audit(
                config=config,
                action="APPROVE",
                release_id=args.release_id,
                manifest_path=candidates[args.release_id].manifest_path,
                reason=args.reason,
                safety=safety,
                approved=False,
                forced=False,
                approval_before=approval_before,
                approval_after=store.approved_release(),
                message="Promotion safety checks failed",
            )
            payload = {
                "approved": False,
                "message": "promotion safety checks failed; rerun with --force to override",
                "promotion_safety": safety.public_dict(),
                "audit_path": str(audit.path),
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 1
            raise SystemExit(payload["message"])
        release = store.approve_release(args.release_id, reason=args.reason)
        approval_after = store.approved_release()
        resolved = resolve_approved_manifest(
            release_store=store,
            manifest_dir=manifest_dir,
        )
        audit = write_promotion_audit(
            config=config,
            action="APPROVE",
            release_id=args.release_id,
            manifest_path=resolved.manifest_path,
            reason=args.reason,
            safety=safety,
            approved=True,
            forced=bool(args.force),
            approval_before=approval_before,
            approval_after=approval_after,
            message="Promotion approved",
        )
        payload = {
            "approved": approval_after.__dict__ if approval_after is not None else None,
            "release": {
                "release_id": release.release_id,
                "health": release.health.value,
                "reason": release.reason,
                "updated_at": release.updated_at,
            },
            "manifest_path": str(resolved.manifest_path),
            "forced": bool(args.force),
            "promotion_safety": safety.public_dict(),
            "audit_path": str(audit.path),
        }
        return _print(payload, json_output=args.json)

    if args.command == "audits":
        audits = list_promotion_audits(config, limit=args.limit)
        payload = {
            "audit_dir": str(config.data_dir / "release_promotions"),
            "audits": [audit.public_dict() for audit in audits],
        }
        return _print(payload, json_output=args.json)

    if args.command == "audit":
        payload = read_promotion_audit(config, args.name)
        return _print(payload, json_output=args.json)

    if args.command == "prune-audits":
        retention = apply_promotion_audit_retention(
            config,
            days=args.days or config.retention_days,
            dry_run=not args.apply,
        )
        return _print({"retention": retention.public_dict()}, json_output=args.json)

    candidates = list_manifest_releases(
        release_store=store,
        manifest_dir=manifest_dir,
    )
    payload = {
        "approved_release": (
            store.approved_release().__dict__
            if store.approved_release() is not None
            else None
        ),
        "releases": [candidate.public_dict() for candidate in candidates],
    }
    return _print(payload, json_output=args.json)


def _print(payload, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if "releases" in payload:
        approved = payload["approved_release"]
        print(f"approved={approved['release_id'] if approved else 'none'}")
        for release in payload["releases"]:
            marker = "*" if release["approved"] else "-"
            print(
                "{marker} {release_id} health={health} manifest={manifest_path}".format(
                    marker=marker,
                    release_id=release["release_id"],
                    health=release["health"],
                    manifest_path=release["manifest_path"],
                )
            )
        return 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and approve local protocol release manifests.",
    )
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    current = subparsers.add_parser("current")
    current.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    check = subparsers.add_parser("check")
    check.add_argument("release_id")
    check.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    approve = subparsers.add_parser("approve")
    approve.add_argument("release_id")
    approve.add_argument("--reason", default="operator_approved")
    approve.add_argument("--force", action="store_true")
    approve.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    audits = subparsers.add_parser("audits")
    audits.add_argument("--limit", type=int, default=25)
    audits.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    audit = subparsers.add_parser("audit")
    audit.add_argument("name")
    audit.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    prune_audits = subparsers.add_parser("prune-audits")
    prune_audits.add_argument("--days", type=int, default=None)
    prune_audits.add_argument("--apply", action="store_true")
    prune_audits.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser.set_defaults(command="list")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
