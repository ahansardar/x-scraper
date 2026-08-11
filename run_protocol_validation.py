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
from xingestion.protocol_validation import build_capture_replay_comparison_report
from xingestion.protocol_validation import build_protocol_validation_report
from xingestion.protocol_validation import run_direct_replays_for_browser_captures
from xingestion.protocol_validation import write_protocol_validation_report
from xingestion.releases import ReleaseStore, resolve_approved_manifest
from xingestion.secrets import resolve_web_session_auth
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.runtime import UrllibJsonTransport, load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="protocol-validation", console=False)
    release_store = ReleaseStore(config.sqlite_path)
    resolved_release = resolve_approved_manifest(
        release_store=release_store,
        manifest_dir=ROOT / "protocol_releases",
    )
    manifest = resolved_release.manifest
    report = build_protocol_validation_report(
        raw_evidence_dir=None if args.fixtures_only else config.raw_evidence_dir,
        parser_revision_id=manifest.bindings[0].recipe.parser.revision_id,
        limit=args.limit,
        include_fixtures=not args.raw_only,
    )
    payload = report.public_dict()
    comparison = None
    direct_replay = None
    if args.compare_captures:
        direct_replay = run_direct_replays_for_browser_captures(
            raw_evidence_dir=config.raw_evidence_dir,
            manifest=manifest,
            auth=resolve_web_session_auth(config),
            transport=UrllibJsonTransport(),
            raw_evidence_sink=FileRawEvidenceSink(config.raw_evidence_dir),
            limit=args.limit,
        )
        comparison = build_capture_replay_comparison_report(
            raw_evidence_dir=config.raw_evidence_dir,
            limit=args.limit,
        )
        payload["direct_replay"] = direct_replay.public_dict()
        payload["capture_replay_comparison"] = comparison.public_dict()
    if args.json:
        if args.write:
            path = write_protocol_validation_report(
                report,
                report_dir=config.data_dir / "protocol_validation",
            )
            payload["saved_path"] = str(path)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "Protocol validation ok={ok} checked={checked} failed={failed} parser={parser}".format(
                ok=payload["ok"],
                checked=payload["checked_sources"],
                failed=payload["failed_sources"],
                parser=payload["parser_revision_id"],
            )
        )
        for result in payload["results"]:
            print(
                "{status} {source_type} tweets={tweets} cursor={cursor} structural={structural} type={type_fp} {source}".format(
                    status="PASS" if result["ok"] else "FAIL",
                    source_type=result["source_type"],
                    tweets=result["tweet_count"],
                    cursor=result["bottom_cursor_present"],
                    structural=result["structural_fingerprint"],
                    type_fp=result["typename_fingerprint"],
                    source=result["source"],
                )
            )
            for warning in result["warnings"]:
                print(f"  warning={warning}")
            if result["error"]:
                print(f"  error={result['error']}")
        if args.write:
            path = write_protocol_validation_report(
                report,
                report_dir=config.data_dir / "protocol_validation",
            )
            print(f"saved={path}")
    direct_replay_ok = direct_replay is None or direct_replay.ok
    comparison_ok = comparison is None or comparison.ok
    return 0 if report.ok and direct_replay_ok and comparison_ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate SEARCH_TWEETS parser output against fixtures and local raw evidence.",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixtures-only", action="store_true")
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--compare-captures", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
