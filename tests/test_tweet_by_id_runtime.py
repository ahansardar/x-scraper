import dataclasses
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest
from xingestion.xprotocol.runtime import (
    ProtocolError,
    TweetByIdRequest,
    WebSessionAuth,
    build_tweet_by_id_request,
    parse_tweet_by_id_result,
    validate_tweet_by_id_recipe_binding,
)

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "tweet_by_id" / "tweet_result_by_rest_id_regression.json"


def load_recipe():
    manifest = ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )
    for binding in manifest.bindings:
        if binding.capability_id == CapabilityId.TWEET_BY_ID:
            return binding.recipe
    raise AssertionError("no TWEET_BY_ID binding in manifest")


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class TweetByIdRuntimeTests(unittest.TestCase):
    def test_builds_protocol_http_request_from_recipe(self):
        http_request = build_tweet_by_id_request(
            recipe=load_recipe(),
            auth=WebSessionAuth(
                auth_token="auth-token",
                ct0="csrf-token",
                bearer_token="bearer-token",
            ),
            request=TweetByIdRequest(tweet_id="2001"),
        )

        self.assertEqual(http_request.method, "POST")
        self.assertTrue(http_request.url.endswith("/TweetResultByRestId"))
        self.assertEqual(http_request.headers["x-csrf-token"], "csrf-token")
        self.assertIn("auth_token=auth-token", http_request.headers["cookie"])
        self.assertEqual(http_request.json_body["variables"]["tweetId"], "2001")

    def test_rejects_missing_auth_and_non_numeric_tweet_id_before_network(self):
        recipe = load_recipe()

        with self.assertRaisesRegex(ValueError, "auth_token"):
            build_tweet_by_id_request(
                recipe=recipe,
                auth=WebSessionAuth("", "csrf-token", "bearer-token"),
                request=TweetByIdRequest(tweet_id="2001"),
            )

        with self.assertRaisesRegex(ValueError, "tweet_id"):
            build_tweet_by_id_request(
                recipe=recipe,
                auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                request=TweetByIdRequest(tweet_id="not-a-number"),
            )

    def test_parses_a_found_tweet_from_the_fixture(self):
        result = parse_tweet_by_id_result(load_fixture())

        self.assertTrue(result.found)
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(result.tweet.tweet_id, "2001")
        self.assertEqual(result.tweet.username, "protocol_user")
        self.assertEqual(result.tweet.like_count, 31)
        self.assertEqual(result.tweet.view_count, "5100")
        self.assertEqual(
            result.tweet.media_urls,
            ("https://pbs.twimg.com/media/sample-by-id.jpg",),
        )
        self.assertEqual(result.tweet.canonical_url, "https://x.com/protocol_user/status/2001")

    def test_parses_not_found_when_result_is_absent(self):
        result = parse_tweet_by_id_result({"data": {"tweetResult": {}}})

        self.assertFalse(result.found)
        self.assertEqual(result.unavailable_reason, "NOT_FOUND")
        self.assertIsNone(result.tweet)

    def test_parses_tombstoned_tweet_as_not_found(self):
        result = parse_tweet_by_id_result(
            {
                "data": {
                    "tweetResult": {
                        "result": {
                            "__typename": "TweetTombstone",
                            "tombstone": {"text": {"text": "This Tweet was deleted."}},
                        }
                    }
                }
            }
        )

        self.assertFalse(result.found)
        self.assertEqual(result.unavailable_reason, "TOMBSTONE")

    def test_parses_unavailable_tweet_with_reason(self):
        result = parse_tweet_by_id_result(
            {
                "data": {
                    "tweetResult": {
                        "result": {
                            "__typename": "TweetUnavailable",
                            "reason": "Protected",
                        }
                    }
                }
            }
        )

        self.assertFalse(result.found)
        self.assertEqual(result.unavailable_reason, "Protected")

    def test_validate_recipe_binding_passes_for_the_pinned_recipe(self):
        self.assertEqual(validate_tweet_by_id_recipe_binding(load_recipe()), ())

    def test_validate_recipe_binding_flags_undeclared_missing_headers(self):
        recipe = load_recipe()
        mutated_transaction_profile = dataclasses.replace(
            recipe.transaction_profile,
            required_headers=(*recipe.transaction_profile.required_headers, "x-made-up-header"),
        )
        mutated = dataclasses.replace(recipe, transaction_profile=mutated_transaction_profile)

        problems = validate_tweet_by_id_recipe_binding(mutated)

        self.assertEqual(len(problems), 1)
        self.assertIn("x-made-up-header", problems[0])

    def test_validate_recipe_binding_flags_auth_material_mismatch(self):
        recipe = load_recipe()
        mutated_auth_profile = dataclasses.replace(
            recipe.auth_profile, required_material=("auth_token", "ct0")
        )
        mutated = dataclasses.replace(recipe, auth_profile=mutated_auth_profile)

        problems = validate_tweet_by_id_recipe_binding(mutated)

        self.assertEqual(len(problems), 1)
        self.assertIn("bearer_token", problems[0])


if __name__ == "__main__":
    unittest.main()
