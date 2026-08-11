import tempfile
import unittest
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.sessions import SessionHealth, SessionStore, import_session_registry, load_session_registry


class SessionStoreTests(unittest.TestCase):
    def test_upsert_session_stores_secret_reference_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")

            session = store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
                network_context="direct",
            )

            self.assertEqual(session.health, SessionHealth.HEALTHY)
            self.assertEqual(session.credential_ref, "secret:x/session-1")
            self.assertIsNone(session.lease_token)
            self.assertEqual(session.attempt_count, 0)
            self.assertEqual(session.success_count, 0)
            self.assertEqual(session.failure_count, 0)
            self.assertIsNone(session.last_error_class)

    def test_rejects_raw_secret_material_as_credential_ref(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")

            with self.assertRaisesRegex(ValueError, "secret reference"):
                store.upsert_session(
                    session_id="session-1",
                    account_label="account",
                    credential_ref="auth_token=raw",
                )

    def test_acquire_and_release_healthy_session_lease(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )

            leased = store.acquire_session(owner="worker-a", lease_seconds=60)
            blocked = store.acquire_session(owner="worker-b", lease_seconds=60)
            store.release_session(leased.session_id, leased.lease_token)
            leased_again = store.acquire_session(owner="worker-b", lease_seconds=60)

            self.assertEqual(leased.lease_owner, "worker-a")
            self.assertTrue(leased.lease_token.startswith("session-lease-"))
            self.assertIsNone(blocked)
            self.assertEqual(leased_again.lease_owner, "worker-b")

    def test_update_health_marks_session_unavailable_for_acquisition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )

            updated = store.update_health(
                "session-1",
                health=SessionHealth.AUTH_EXPIRED,
                reason="auth rejected",
            )
            leased = store.acquire_session(owner="worker-a", lease_seconds=60)

            self.assertEqual(updated.health, SessionHealth.AUTH_EXPIRED)
            self.assertIsNone(leased)

    def test_acquire_skips_session_until_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
            past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

            cooled = store.update_health(
                "session-1",
                health=SessionHealth.DEGRADED,
                reason="rate limited",
                cooldown_until=future,
            )
            blocked = store.acquire_session(owner="worker-a", lease_seconds=60)
            restored = store.update_health(
                "session-1",
                health=SessionHealth.DEGRADED,
                reason="cooldown elapsed",
                cooldown_until=past,
            )
            leased = store.acquire_session(owner="worker-b", lease_seconds=60)

            self.assertEqual(cooled.cooldown_until, future)
            self.assertIsNone(blocked)
            self.assertEqual(restored.cooldown_until, past)
            self.assertEqual(leased.session_id, "session-1")
            self.assertEqual(leased.health, SessionHealth.DEGRADED)

    def test_records_attempt_success_and_failure_visibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "sessions.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )

            started = store.record_attempt_started("session-1")
            failed = store.record_attempt_failure(
                "session-1",
                error_class="RATE_LIMITED",
                error_message="X returned HTTP 429",
            )
            store.record_attempt_started("session-1")
            succeeded = store.record_attempt_success("session-1")

            self.assertEqual(started.attempt_count, 1)
            self.assertIsNotNone(started.last_attempt_at)
            self.assertEqual(failed.failure_count, 1)
            self.assertEqual(failed.last_error_class, "RATE_LIMITED")
            self.assertEqual(failed.last_error_message, "X returned HTTP 429")
            self.assertEqual(succeeded.attempt_count, 2)
            self.assertEqual(succeeded.success_count, 1)
            self.assertEqual(succeeded.failure_count, 1)
            self.assertIsNotNone(succeeded.last_success_at)
            self.assertIsNone(succeeded.last_error_class)

    def test_imports_session_registry_without_exposing_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = root / "sessions.json"
            registry.write_text(
                json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "session-a",
                                "account_label": "account-a",
                                "credential_ref": "file:session-a",
                                "network_context": "direct:iad",
                            },
                            {
                                "session_id": "session-b",
                                "account_label": "account-b",
                                "credential_ref": "file:session-b",
                                "network_context": "direct:sfo",
                                "health": "DISABLED",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store = SessionStore(root / "sessions.sqlite3")

            entries = load_session_registry(registry)
            result = import_session_registry(store=store, path=registry)

            self.assertEqual(len(entries), 2)
            self.assertEqual(result.imported, 2)
            self.assertEqual(store.get_session("session-a").network_context, "direct:iad")
            self.assertEqual(store.get_session("session-b").health, SessionHealth.DISABLED)
            raw = json.dumps(result.public_dict())
            self.assertNotIn("file:session-a", raw)
            self.assertIn("reference_scheme", raw)


if __name__ == "__main__":
    unittest.main()
