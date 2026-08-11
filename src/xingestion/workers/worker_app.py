from __future__ import annotations

from pathlib import Path
import logging
import sys
import time

from xingestion.config import load_app_config
from xingestion.canonical import CanonicalStore
from xingestion.logging_config import configure_logging
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.tasks import SQLiteTaskLedger
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import UrllibJsonTransport, load_env_file, web_session_auth_from_env


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "protocol_releases" / "search_tweets.candidate.json"
LOGGER = logging.getLogger("xingestion.worker")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    logging_settings = configure_logging(config=config, component="worker")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)

    auth = web_session_auth_from_env()
    session_store = SessionStore(config.sqlite_path)
    session_store.upsert_session(
        session_id=config.default_session_id,
        account_label=config.default_account_label,
        credential_ref=config.default_credential_ref,
        network_context=config.default_network_context,
        health=SessionHealth.HEALTHY if not auth.missing_fields() else SessionHealth.AUTH_EXPIRED,
    )

    worker = LocalWorker(
        release_store=ReleaseStore(config.sqlite_path),
        ledger=SQLiteTaskLedger(config.sqlite_path),
        manifest=ProtocolReleaseManifest.from_file(MANIFEST_PATH),
        auth=auth,
        transport=UrllibJsonTransport(),
        raw_evidence_sink=FileRawEvidenceSink(config.raw_evidence_dir),
        canonical_store=CanonicalStore(config.sqlite_path),
        session_store=session_store,
        telemetry_store=ProtocolTelemetryStore(config.sqlite_path),
    )

    once = "--once" in argv
    sleep_seconds = _float_arg(argv, "--sleep", 2.0)
    print(f"X ingestion worker using SQLite: {config.sqlite_path}")
    print(f"Raw evidence directory: {config.raw_evidence_dir}")
    print(f"Log file: {logging_settings.log_file}")
    LOGGER.info(
        "worker starting sqlite=%s raw_evidence=%s once=%s sleep_seconds=%s",
        config.sqlite_path,
        config.raw_evidence_dir,
        once,
        sleep_seconds,
    )

    while True:
        result = worker.process_one()
        if result.processed:
            message = (
                f"processed task={result.task_id} state={result.state} "
                f"error={result.error_class or ''}"
            )
            print(message)
            LOGGER.info(message)
        elif once:
            print("no pending outbox events")
            LOGGER.info("no pending outbox events")
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
