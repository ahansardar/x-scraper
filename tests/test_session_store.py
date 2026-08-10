import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
