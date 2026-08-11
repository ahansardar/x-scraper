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
from xingestion.protocol_validation import build_protocol_validation_report
from xingestion.protocol_validation import write_protocol_validation_report
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import load_env_file


MANIFEST_PATH = ROOT / "protocol_releases" / "search_tweets.candidate.json"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="protocol-validation", console=False)
    manifest = ProtocolReleaseManifest.from_file(MANIFEST_PATH)
    report = build_protocol_validation_report(
        raw_evidence_dir=None if args.fixtures_only else config.raw_evidence_dir,
        parser_revision_id=manifest.bindings[0].recipe.parser.revision_id,
        limit=args.limit,
        include_fixtures=not args.raw_only,
    )
    payload = report.public_dict()
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
    return 0 if report.ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate SEARCH_TWEETS parser output against fixtures and local raw evidence.",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixtures-only", action="store_true")
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
