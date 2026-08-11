from __future__ import annotations

from pathlib import Path
import logging
import sys
import time

from xingestion.config import load_app_config
from xingestion.canonical import CanonicalStore
from xingestion.logging_config import configure_logging
from xingestion.releases import ReleaseStore, resolve_approved_manifest
from xingestion.secrets import build_secret_provider, resolve_web_session_auth
from xingestion.sessions import SessionHealth, SessionStore, import_session_registry
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.tasks import SQLiteTaskLedger
from xingestion.workers import LocalWorker
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.runtime import UrllibJsonTransport, load_env_file


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "protocol_releases"
LOGGER = logging.getLogger("xingestion.worker")


def build_worker(*, config, root: Path = ROOT) -> LocalWorker:
    auth = resolve_web_session_auth(config)
    secret_provider = build_secret_provider(config)
    session_store = SessionStore(config.sqlite_path)
    session_store.upsert_session(
        session_id=config.default_session_id,
        account_label=config.default_account_label,
        credential_ref=config.default_credential_ref,
        network_context=config.default_network_context,
        health=SessionHealth.HEALTHY if not auth.missing_fields() else SessionHealth.AUTH_EXPIRED,
    )
    if config.session_registry_path is not None:
        import_session_registry(store=session_store, path=config.session_registry_path)
    release_store = ReleaseStore(config.sqlite_path)
    resolved_release = resolve_approved_manifest(
        release_store=release_store,
        manifest_dir=root / "protocol_releases",
    )
    return LocalWorker(
        release_store=release_store,
        ledger=SQLiteTaskLedger(config.sqlite_path),
        manifest=resolved_release.manifest,
        auth=auth,
        transport=UrllibJsonTransport(),
        raw_evidence_sink=FileRawEvidenceSink(config.raw_evidence_dir),
        canonical_store=CanonicalStore(config.sqlite_path),
        session_store=session_store,
        telemetry_store=ProtocolTelemetryStore(config.sqlite_path),
        secret_provider=secret_provider,
        required_network_context=config.worker_network_context or None,
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    logging_settings = configure_logging(config=config, component="worker")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)

    worker = build_worker(config=config)

    once = "--once" in argv
    sleep_seconds = _float_arg(argv, "--sleep", 2.0)
    print(f"X ingestion worker using SQLite: {config.sqlite_path}")
    print(f"Raw evidence directory: {config.raw_evidence_dir}")
    if config.worker_network_context:
        print(f"Worker network context: {config.worker_network_context}")
    print(f"Log file: {logging_settings.log_file}")
    LOGGER.info(
        "worker starting sqlite=%s raw_evidence=%s network_context=%s once=%s sleep_seconds=%s",
        config.sqlite_path,
        config.raw_evidence_dir,
        config.worker_network_context or "any",
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
