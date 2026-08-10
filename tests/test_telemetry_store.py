import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.telemetry import ProtocolTelemetryStore


class ProtocolTelemetryStoreTests(unittest.TestCase):
    def test_records_attempts_and_summarizes_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")

            store.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="SUCCESS",
                session_id="session-1",
                tweet_count=2,
                next_cursor_present=True,
                duration_ms=123,
            )
            store.record_attempt(
                task_id="task-2",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="FAILURE",
                session_id="session-1",
                error_class="RATE_LIMITED",
                duration_ms=50,
            )

            summary = store.summary()

            self.assertEqual(summary.total_attempts, 2)
            self.assertEqual(summary.successes, 1)
            self.assertEqual(summary.failures, 1)
            self.assertEqual(summary.errors_by_class["RATE_LIMITED"], 1)

            task_attempts = store.list_for_task("task-2")

            self.assertEqual(len(task_attempts), 1)
            self.assertEqual(task_attempts[0].task_id, "task-2")
            self.assertEqual(task_attempts[0].state, "FAILURE")
            self.assertEqual(task_attempts[0].error_class, "RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
