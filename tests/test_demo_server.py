import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.web.demo_server import DemoSearchTransport
from xrev.runtime import ProtocolHttpRequest


class DemoServerTests(unittest.TestCase):
    def test_demo_transport_returns_parseable_payload_shape(self):
        transport = DemoSearchTransport()
        response = transport.send(
            ProtocolHttpRequest(
                method="POST",
                url="https://x.com/i/api/graphql/test/SearchTimeline",
                headers={},
                json_body={
                    "variables": {
                        "rawQuery": "india",
                        "product": "Top",
                    }
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        encoded = json.dumps(response.json_body)
        self.assertIn("tweet_results", encoded)
        self.assertIn("Bottom", encoded)


if __name__ == "__main__":
    unittest.main()
