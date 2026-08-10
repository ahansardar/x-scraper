from __future__ import annotations

from pathlib import Path
import sys
import time

from xingestion.config import load_app_config
from xingestion.canonical import CanonicalStore
from xingestion.tasks import SQLiteTaskLedger
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import UrllibJsonTransport, load_env_file, web_session_auth_from_env


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "protocol_releases" / "search_tweets.candidate.json"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)

    worker = LocalWorker(
        ledger=SQLiteTaskLedger(config.sqlite_path),
        manifest=ProtocolReleaseManifest.from_file(MANIFEST_PATH),
        auth=web_session_auth_from_env(),
        transport=UrllibJsonTransport(),
        raw_evidence_sink=FileRawEvidenceSink(config.raw_evidence_dir),
        canonical_store=CanonicalStore(config.sqlite_path),
    )

    once = "--once" in argv
    sleep_seconds = _float_arg(argv, "--sleep", 2.0)
    print(f"X ingestion worker using SQLite: {config.sqlite_path}")
    print(f"Raw evidence directory: {config.raw_evidence_dir}")

    while True:
        result = worker.process_one()
        if result.processed:
            print(
                f"processed task={result.task_id} state={result.state} "
                f"error={result.error_class or ''}"
            )
        elif once:
            print("no pending outbox events")
            return 0

        if once:
            return 0
        time.sleep(sleep_seconds)


def _float_arg(argv, name, default):
    if name not in argv:
        return default
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ValueError(f"{name} requires a value")
    return float(argv[index + 1])


if __name__ == "__main__":
    raise SystemExit(main())
