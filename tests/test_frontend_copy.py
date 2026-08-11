import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCopyTests(unittest.TestCase):
    def test_frontend_does_not_present_mock_data(self):
        html = (
            ROOT
            / "src"
            / "xingestion"
            / "web"
            / "static"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("Run live acquisition", html)
        self.assertIn("Metrics", html)
        self.assertIn("Sessions", html)
        self.assertIn("Last Error", html)
        self.assertIn("Needs Attention", html)
        self.assertNotIn("mock", html.lower())

    def test_frontend_reports_non_json_api_responses(self):
        js = (
            ROOT
            / "src"
            / "xingestion"
            / "web"
            / "static"
            / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("returned non-JSON", js)
        self.assertIn("parseJsonResponse", js)

    def test_frontend_exposes_session_operator_controls(self):
        js = (
            ROOT
            / "src"
            / "xingestion"
            / "web"
            / "static"
            / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("/api/sessions", js)
        self.assertIn("data-restore-session", js)
        self.assertIn("data-disable-session", js)
        self.assertIn("formatSessionError", js)
        self.assertIn("data-investigate-task", js)
        self.assertIn("renderInvestigation", js)
        self.assertIn("/api/task-actions", js)
        self.assertIn("loadTaskActions", js)
        self.assertIn("taskActionControls", js)
        self.assertIn("data-export-task", js)
        self.assertIn("/export", js)
        self.assertIn("renderSupportExport", js)


if __name__ == "__main__":
    unittest.main()
