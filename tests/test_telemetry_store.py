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
                network_context="direct:iad",
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
                network_context="direct:iad",
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
            self.assertEqual(task_attempts[0].network_context, "direct:iad")
            self.assertEqual(task_attempts[0].error_class, "RATE_LIMITED")

            signals = store.release_error_signals("release-1")

            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].error_class, "RATE_LIMITED")
            self.assertEqual(signals[0].count, 1)
            self.assertEqual(signals[0].distinct_sessions, 1)

            network_summary = store.network_summary()

            self.assertEqual(len(network_summary), 1)
            self.assertEqual(network_summary[0].network_context, "direct:iad")
            self.assertEqual(network_summary[0].total_attempts, 2)
            self.assertEqual(network_summary[0].successes, 1)
            self.assertEqual(network_summary[0].failures, 1)
            self.assertEqual(network_summary[0].failure_rate, 0.5)
            self.assertEqual(network_summary[0].distinct_sessions, 1)
            self.assertIn("RATE_LIMITED", network_summary[0].errors_by_class)

    def test_network_summary_groups_missing_route_as_unassigned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")

            store.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="FAILURE",
                session_id=None,
                error_class="NO_SESSION",
            )

            network_summary = store.network_summary()

            self.assertEqual(network_summary[0].network_context, "unassigned")
            self.assertEqual(network_summary[0].failures, 1)
            self.assertEqual(network_summary[0].errors_by_class["NO_SESSION"], 1)

    def test_network_summary_can_filter_by_release(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")
            store.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="SUCCESS",
                session_id="session-1",
                network_context="direct",
            )
            store.record_attempt(
                task_id="task-2",
                capability_id="SEARCH_TWEETS",
                release_id="release-2",
                recipe_revision_id="recipe-1",
                state="FAILURE",
                session_id="session-1",
                network_context="proxy:pool-a",
                error_class="RATE_LIMITED",
            )

            network_summary = store.network_summary(release_id="release-1")

            self.assertEqual(len(network_summary), 1)
            self.assertEqual(network_summary[0].network_context, "direct")

    def test_recent_attempts_orders_newest_first_and_respects_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")
            for index in range(5):
                store.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id="release-1",
                    recipe_revision_id="recipe-1",
                    state="SUCCESS" if index % 2 == 0 else "FAILURE",
                    session_id="session-1",
                )

            recent = store.recent_attempts("release-1", limit=3)

            self.assertEqual(len(recent), 3)
            self.assertEqual([a.task_id for a in recent], ["task-4", "task-3", "task-2"])

    def test_recent_attempts_filters_by_recipe_revision_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")
            store.record_attempt(
                task_id="old-recipe-task",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-old",
                state="FAILURE",
                session_id="session-1",
                error_class="OPERATION_NOT_FOUND",
            )
            store.record_attempt(
                task_id="new-recipe-task",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-new",
                state="SUCCESS",
                session_id="session-1",
            )

            recent = store.recent_attempts(
                "release-1", recipe_revision_id="recipe-new", limit=10
            )

            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].task_id, "new-recipe-task")

    def test_recent_attempts_rejects_non_positive_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProtocolTelemetryStore(Path(temp_dir) / "telemetry.sqlite3")
            with self.assertRaises(ValueError):
                store.recent_attempts("release-1", limit=0)


if __name__ == "__main__":
    unittest.main()
