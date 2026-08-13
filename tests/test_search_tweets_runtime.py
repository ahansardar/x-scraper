import dataclasses
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import (
    ProtocolError,
    RetryDisposition,
    SearchTweetsRequest,
    WebSessionAuth,
    build_search_timeline_request,
    parse_search_tweets_page,
    validate_recipe_binding,
    validate_search_tweets_pagination,
)


def load_recipe():
    manifest = ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )
    return manifest.bindings[0].recipe


class SearchTweetsRuntimeTests(unittest.TestCase):
    def test_builds_protocol_http_request_from_recipe(self):
        http_request = build_search_timeline_request(
            recipe=load_recipe(),
            auth=WebSessionAuth(
                auth_token="auth-token",
                ct0="csrf-token",
                bearer_token="bearer-token",
            ),
            request=SearchTweetsRequest(
                query="india lang:en",
                product="Latest",
                count=25,
                cursor="opaque-cursor",
            ),
        )

        self.assertEqual(http_request.method, "POST")
        self.assertTrue(http_request.url.endswith("/SearchTimeline"))
        self.assertIn("PusO6nN_nUSAsfJktZJd9w", http_request.url)
        self.assertEqual(http_request.headers["x-csrf-token"], "csrf-token")
        self.assertIn("auth_token=auth-token", http_request.headers["cookie"])
        self.assertEqual(
            http_request.json_body["variables"]["rawQuery"],
            "india lang:en",
        )
        self.assertEqual(http_request.json_body["variables"]["cursor"], "opaque-cursor")
        self.assertIn(
            "responsive_web_graphql_timeline_navigation_enabled",
            http_request.json_body["features"],
        )

    def test_rejects_missing_auth_and_invalid_count_before_network(self):
        recipe = load_recipe()

        with self.assertRaisesRegex(ValueError, "auth_token"):
            build_search_timeline_request(
                recipe=recipe,
                auth=WebSessionAuth("", "csrf-token", "bearer-token"),
                request=SearchTweetsRequest(query="india"),
            )

        with self.assertRaisesRegex(ValueError, "count"):
            build_search_timeline_request(
                recipe=recipe,
                auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                request=SearchTweetsRequest(query="india", count=0),
            )

    def test_parses_tweets_and_bottom_cursor(self):
        payload = {
            "data": {
                "search_by_raw_query": {
                    "search_timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "__typename": "Tweet",
                                                            "rest_id": "123",
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "core": {
                                                                            "screen_name": "alice",
                                                                            "name": "Alice",
                                                                        }
                                                                    }
                                                                }
                                                            },
                                                            "legacy": {
                                                                "id_str": "123",
                                                                "full_text": "hello",
                                                                "created_at": "Mon Aug 10 12:00:00 +0000 2026",
                                                                "favorite_count": 3,
                                                                "retweet_count": 2,
                                                                "reply_count": 1,
                                                                "quote_count": 4,
                                                                "bookmark_count": 5,
                                                                "extended_entities": {
                                                                    "media": [
                                                                        {
                                                                            "media_url_https": "https://img.example/1.jpg"
                                                                        }
                                                                    ]
                                                                },
                                                            },
                                                            "views": {"count": "10"},
                                                        }
                                                    }
                                                }
                                            }
                                        },
                                        {
                                            "content": {
                                                "cursorType": "Bottom",
                                                "value": "next-cursor",
                                            }
                                        },
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

        page = parse_search_tweets_page(payload)

        self.assertEqual(page.next_cursor, "next-cursor")
        self.assertTrue(page.cursor_present)
        self.assertEqual(len(page.tweets), 1)
        tweet = page.tweets[0]
        self.assertEqual(tweet.tweet_id, "123")
        self.assertEqual(tweet.username, "alice")
        self.assertEqual(tweet.like_count, 3)
        self.assertEqual(tweet.media_urls, ("https://img.example/1.jpg",))
        self.assertEqual(tweet.canonical_url, "https://x.com/alice/status/123")

    def test_validates_pagination_cursor_states(self):
        missing_cursor_page = parse_search_tweets_page({"entries": []})
        self.assertFalse(missing_cursor_page.cursor_present)
        self.assertIsNone(
            validate_search_tweets_pagination(
                missing_cursor_page,
                expect_more=False,
            )
        )

        with self.assertRaises(ProtocolError) as missing_error:
            validate_search_tweets_pagination(
                missing_cursor_page,
                expect_more=True,
            )

        self.assertEqual(
            missing_error.exception.error_class,
            "PAGINATION_CURSOR_MISSING",
        )
        self.assertEqual(
            missing_error.exception.retry_disposition,
            RetryDisposition.NEVER,
        )

        empty_cursor_page = parse_search_tweets_page(
            {
                "entries": [
                    {"content": {"cursorType": "Bottom", "value": ""}},
                ]
            }
        )
        self.assertTrue(empty_cursor_page.cursor_present)
        self.assertEqual(empty_cursor_page.next_cursor, "")
        self.assertEqual(
            validate_search_tweets_pagination(
                empty_cursor_page,
                expect_more=False,
            ),
            "",
        )

        with self.assertRaises(ProtocolError) as empty_error:
            validate_search_tweets_pagination(
                empty_cursor_page,
                expect_more=True,
            )

        self.assertEqual(
            empty_error.exception.error_class,
            "PAGINATION_EMPTY_CONTINUATION",
        )

        loop_cursor_page = parse_search_tweets_page(
            {
                "entries": [
                    {"content": {"cursorType": "Bottom", "value": "cursor-1"}},
                ]
            }
        )

        with self.assertRaises(ProtocolError) as loop_error:
            validate_search_tweets_pagination(
                loop_cursor_page,
                expect_more=True,
                seen_cursors=("cursor-1",),
            )

        self.assertEqual(
            loop_error.exception.error_class,
            "PAGINATION_CURSOR_LOOP",
        )

    def test_duplicate_tweet_entries_merge_richer_engagement_metrics(self):
        def result(likes, reposts, replies, quotes, views=None):
            payload = {
                "__typename": "Tweet",
                "rest_id": "123",
                "core": {
                    "user_results": {
                        "result": {
                            "core": {
                                "screen_name": "alice",
                                "name": "Alice",
                            }
                        }
                    }
                },
                "legacy": {
                    "id_str": "123",
                    "full_text": "hello",
                    "created_at": "Mon Aug 10 12:00:00 +0000 2026",
                    "favorite_count": likes,
                    "retweet_count": reposts,
                    "reply_count": replies,
                    "quote_count": quotes,
                    "bookmark_count": 0,
                },
                "views": {"state": "Enabled"},
            }
            if views is not None:
                payload["views"] = {"count": str(views), "state": "EnabledWithCount"}
            return payload

        page = parse_search_tweets_page(
            {
                "entries": [
                    {"tweet_results": {"result": result(0, 0, 0, 0)}},
                    {"tweet_results": {"result": result(5, 2, 3, 1, 99)}},
                ]
            }
        )

        self.assertEqual(len(page.tweets), 1)
        tweet = page.tweets[0]
        self.assertEqual(tweet.like_count, 5)
        self.assertEqual(tweet.repost_count, 2)
        self.assertEqual(tweet.reply_count, 3)
        self.assertEqual(tweet.quote_count, 1)
        self.assertEqual(tweet.view_count, "99")

    def test_validate_recipe_binding_passes_for_the_pinned_recipe(self):
        self.assertEqual(validate_recipe_binding(load_recipe()), ())

    def test_validate_recipe_binding_flags_undeclared_missing_headers(self):
        recipe = load_recipe()
        mutated_transaction_profile = dataclasses.replace(
            recipe.transaction_profile,
            required_headers=(*recipe.transaction_profile.required_headers, "x-made-up-header"),
        )
        mutated = dataclasses.replace(recipe, transaction_profile=mutated_transaction_profile)

        problems = validate_recipe_binding(mutated)

        self.assertEqual(len(problems), 1)
        self.assertIn("x-made-up-header", problems[0])

    def test_validate_recipe_binding_flags_auth_material_mismatch(self):
        recipe = load_recipe()
        mutated_auth_profile = dataclasses.replace(
            recipe.auth_profile, required_material=("auth_token", "ct0")
        )
        mutated = dataclasses.replace(recipe, auth_profile=mutated_auth_profile)

        problems = validate_recipe_binding(mutated)

        self.assertEqual(len(problems), 1)
        self.assertIn("bearer_token", problems[0])

    def test_validate_recipe_binding_flags_extra_declared_auth_material(self):
        recipe = load_recipe()
        mutated_auth_profile = dataclasses.replace(
            recipe.auth_profile,
            required_material=(*recipe.auth_profile.required_material, "totally_made_up_field"),
        )
        mutated = dataclasses.replace(recipe, auth_profile=mutated_auth_profile)

        problems = validate_recipe_binding(mutated)

        self.assertEqual(len(problems), 1)
        self.assertIn("totally_made_up_field", problems[0])


if __name__ == "__main__":
    unittest.main()
