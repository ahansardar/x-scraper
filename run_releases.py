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
    list_manifest_releases,
    resolve_approved_manifest,
)
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
        release = store.approve_release(args.release_id, reason=args.reason)
        resolved = resolve_approved_manifest(
            release_store=store,
            manifest_dir=manifest_dir,
        )
        payload = {
            "approved": store.approved_release().__dict__,
            "release": {
                "release_id": release.release_id,
                "health": release.health.value,
                "reason": release.reason,
                "updated_at": release.updated_at,
            },
            "manifest_path": str(resolved.manifest_path),
        }
        return _print(payload, json_output=args.json)

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
    approve = subparsers.add_parser("approve")
    approve.add_argument("release_id")
    approve.add_argument("--reason", default="operator_approved")
    approve.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser.set_defaults(command="list")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
