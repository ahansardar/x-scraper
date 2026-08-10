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
        self.assertNotIn("mock", html.lower())


if __name__ == "__main__":
    unittest.main()
