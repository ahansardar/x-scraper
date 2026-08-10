import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.sessions import SessionHealth, SessionStore


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


if __name__ == "__main__":
    unittest.main()
