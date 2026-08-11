import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityPlannerError,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest, RevisionStatus


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class CapabilityPlannerTests(unittest.TestCase):
    def test_plans_search_tweets_without_exposing_graphql_in_public_plan(self):
        planner = CapabilityPlanner(load_manifest())
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(
                query="india lang:en",
                product="Latest",
                cursor="opaque",
                page_size=25,
            ),
            traffic_priority="HIGH",
        )

        plan = planner.plan(request)
        public_plan = plan.public_dict()

        self.assertEqual(plan.capability_id, CapabilityId.SEARCH_TWEETS)
        self.assertEqual(plan.required_auth_class, "AUTHORIZED_WEB_SESSION")
        self.assertEqual(plan.cursor, "opaque")
        self.assertEqual(plan.page_size, 25)
        self.assertEqual(plan.max_pages, 1)
        self.assertEqual(plan.page_number, 1)
        self.assertEqual(public_plan["traffic_priority"], "HIGH")
        self.assertNotIn("operation_id", public_plan)
        self.assertNotIn("url_template", public_plan)
        self.assertNotIn("features", public_plan)

    def test_validates_stable_capability_request(self):
        planner = CapabilityPlanner(load_manifest())

        with self.assertRaisesRegex(CapabilityPlannerError, "query"):
            planner.plan(
                CapabilityRequest(
                    capability_id=CapabilityId.SEARCH_TWEETS,
                    contract_version=1,
                    payload=SearchTweetsInput(query=" "),
                )
            )

        with self.assertRaisesRegex(CapabilityPlannerError, "page_size"):
            planner.plan(
                CapabilityRequest(
                    capability_id=CapabilityId.SEARCH_TWEETS,
                    contract_version=1,
                    payload=SearchTweetsInput(query="india", page_size=99),
                )
            )

        with self.assertRaisesRegex(CapabilityPlannerError, "max_pages"):
            planner.plan(
                CapabilityRequest(
                    capability_id=CapabilityId.SEARCH_TWEETS,
                    contract_version=1,
                    payload=SearchTweetsInput(query="india", max_pages=0),
                )
            )

        with self.assertRaisesRegex(CapabilityPlannerError, "page_number"):
            planner.plan(
                CapabilityRequest(
                    capability_id=CapabilityId.SEARCH_TWEETS,
                    contract_version=1,
                    payload=SearchTweetsInput(query="india", max_pages=2, page_number=3),
                )
            )

    def test_rejects_ineligible_manifest_status(self):
        planner = CapabilityPlanner(
            load_manifest(),
            allowed_statuses={RevisionStatus.APPROVED},
        )

        with self.assertRaisesRegex(CapabilityPlannerError, "not eligible"):
            planner.plan(
                CapabilityRequest(
                    capability_id=CapabilityId.SEARCH_TWEETS,
                    contract_version=1,
                    payload=SearchTweetsInput(query="india"),
                )
            )


if __name__ == "__main__":
    unittest.main()
