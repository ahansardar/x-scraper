import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.errors import ErrorScope, ErrorSeverity, classify_error, envelope_from_task_error


class RuntimeErrorClassificationTests(unittest.TestCase):
    def test_known_protocol_error_gets_operator_action(self):
        envelope = classify_error(
            "OPERATION_NOT_FOUND",
            message="X returned HTTP 404",
            status_code=404,
            scope_hint="OPERATION",
        )

        self.assertEqual(envelope.severity, ErrorSeverity.CRITICAL)
        self.assertEqual(envelope.scope, ErrorScope.PROTOCOL)
        self.assertFalse(envelope.retryable)
        self.assertEqual(
            envelope.operator_action,
            "investigate_protocol_release_and_consider_quarantine",
        )
        self.assertEqual(envelope.public_dict()["status_code"], 404)

    def test_task_error_without_runtime_envelope_is_classified(self):
        envelope = envelope_from_task_error(
            {
                "error_class": "SESSION_UNAVAILABLE",
                "message": "No healthy session lease is available",
            }
        )

        self.assertIsNotNone(envelope)
        self.assertEqual(envelope.scope, ErrorScope.SESSION)
        self.assertTrue(envelope.retryable)


if __name__ == "__main__":
    unittest.main()
