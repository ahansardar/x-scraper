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
from xingestion.sessions import SessionStore, import_session_registry
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="sessions", console=False)
    store = SessionStore(config.sqlite_path)

    if args.import_registry:
        path = Path(args.import_registry).expanduser().resolve()
        payload = import_session_registry(store=store, path=path).public_dict()
    else:
        payload = {
            "sessions": [_safe_session_dict(session) for session in store.list_sessions()]
        }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List or import authorized session metadata without printing secret values.",
    )
    parser.add_argument("--import-registry")
    parser.add_argument("--json", action="store_true")
    return parser


def _safe_session_dict(session) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "account_label": session.account_label,
        "reference_configured": bool(session.credential_ref),
        "reference_scheme": (
            session.credential_ref.split(":", 1)[0]
            if ":" in session.credential_ref
            else "unknown"
        ),
        "network_context": session.network_context,
        "network_policy": session.network_policy.public_dict(),
        "health": session.health.value,
        "attempt_count": session.attempt_count,
        "success_count": session.success_count,
        "failure_count": session.failure_count,
        "cooldown_until": session.cooldown_until,
    }


def _print_human(payload: dict[str, object]) -> None:
    sessions = payload.get("sessions", [])
    if "imported" in payload:
        print(f"Imported {payload['imported']} sessions from {payload['source']}")
    if not sessions:
        print("No sessions found.")
        return
    for session in sessions:
        print(
            "{session_id} health={health} account={account_label} "
            "network={network_context} reference={reference_scheme}".format(**session)
        )


if __name__ == "__main__":
    raise SystemExit(main())
