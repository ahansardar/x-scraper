import os
import csv
import json
import time
import random
import requests
from pathlib import Path


def load_env_file(path=".env"):
    env_path = Path(path)

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

# =========================
# CONFIG
# =========================

BASE_URL = "https://x.com/i/api/graphql/aItCniN7nsU1ly1OjaKq2Q/ExplorePage"

AUTH_TOKEN = os.getenv("X_AUTH_TOKEN", "")
CT0 = os.getenv("X_CT0", "")
BEARER = os.getenv("X_BEARER", "")

HEADERS = {
    "authorization": f"Bearer {BEARER}",
    "x-csrf-token": CT0,
    "cookie": f"auth_token={AUTH_TOKEN}; ct0={CT0}",
    "referer": "https://x.com/explore",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}


def require_auth():
    missing = [
        key
        for key, value in {
            "X_AUTH_TOKEN": AUTH_TOKEN,
            "X_CT0": CT0,
            "X_BEARER": BEARER,
        }.items()
        if not value
    ]

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variable(s): {joined}")

FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "rweb_cashtags_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "rweb_cashtags_composer_attachment_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "rweb_conversational_replies_downvote_enabled": False,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": True,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


# =========================
# REQUEST
# =========================

def fetch_page(cursor=""):
    variables = {
        "cursor": cursor
    }

    params = {
        "variables": json.dumps(
            variables,
            separators=(",", ":")
        ),
        "features": json.dumps(
            FEATURES,
            separators=(",", ":")
        )
    }

    response = requests.get(
        BASE_URL,
        headers=HEADERS,
        params=params,
        timeout=30
    )

    print("HTTP:", response.status_code)

    if response.status_code != 200:
        print(response.text[:2000])

    response.raise_for_status()

    return response.json()


# =========================
# TWEET EXTRACTION
# =========================

def make_tweet(result):
    """
    Converts an X tweet result object into a flat dictionary.
    """

    if not isinstance(result, dict):
        return None

    # Visibility wrapper
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy")

    if not legacy:
        return None

    # Author
    user_result = (
        result
        .get("core", {})
        .get("user_results", {})
        .get("result", {})
    )

    user_core = user_result.get("core", {})
    user_legacy = user_result.get("legacy", {})

    username = (
        user_core.get("screen_name")
        or user_legacy.get("screen_name")
        or ""
    )

    name = (
        user_core.get("name")
        or user_legacy.get("name")
        or ""
    )

    tweet_id = (
        result.get("rest_id")
        or legacy.get("id_str")
        or ""
    )

    # Views
    views = (
        result
        .get("views", {})
        .get("count", "")
    )

    return {
        "id": tweet_id,
        "username": username,
        "name": name,
        "text": legacy.get("full_text", ""),
        "created_at": legacy.get("created_at", ""),
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "quotes": legacy.get("quote_count", 0),
        "views": views,
        "url": (
            f"https://x.com/{username}/status/{tweet_id}"
            if username and tweet_id
            else ""
        )
    }


def recursive_find_tweets(obj, tweets, seen_ids):
    """
    Recursively searches the entire response for
    tweet_results -> result objects.
    """

    if isinstance(obj, dict):

        # Common X tweet container
        if "tweet_results" in obj:
            result = (
                obj.get("tweet_results", {})
                .get("result", {})
            )

            tweet = make_tweet(result)

            if tweet:
                tweet_id = tweet["id"]

                if tweet_id and tweet_id not in seen_ids:
                    seen_ids.add(tweet_id)
                    tweets.append(tweet)

        # Sometimes a tweet result appears directly
        if obj.get("__typename") in (
            "Tweet",
            "TweetWithVisibilityResults"
        ):
            tweet = make_tweet(obj)

            if tweet:
                tweet_id = tweet["id"]

                if tweet_id and tweet_id not in seen_ids:
                    seen_ids.add(tweet_id)
                    tweets.append(tweet)

        # Continue recursion
        for value in obj.values():
            recursive_find_tweets(
                value,
                tweets,
                seen_ids
            )

    elif isinstance(obj, list):

        for item in obj:
            recursive_find_tweets(
                item,
                tweets,
                seen_ids
            )


# =========================
# CURSOR EXTRACTION
# =========================

def recursive_find_bottom_cursor(obj):
    """
    Finds Bottom cursor anywhere in the Explore response.
    """

    if isinstance(obj, dict):

        if obj.get("cursorType") == "Bottom":
            value = obj.get("value")

            if value:
                return value

        for value in obj.values():
            result = recursive_find_bottom_cursor(value)

            if result:
                return result

    elif isinstance(obj, list):

        for item in obj:
            result = recursive_find_bottom_cursor(item)

            if result:
                return result

    return None


# =========================
# PARSE PAGE
# =========================

def parse_page(data):
    tweets = []
    seen_ids = set()

    recursive_find_tweets(
        data,
        tweets,
        seen_ids
    )

    cursor = recursive_find_bottom_cursor(data)

    return tweets, cursor


# =========================
# MAIN
# =========================

all_tweets = []
global_seen_ids = set()

require_auth()

cursor = ""
page = 1

MAX_PAGES = 10

while page <= MAX_PAGES:

    print(f"\nFetching Explore page {page}...")

    data = fetch_page(cursor)

    # Save latest response for debugging
    with open(
        f"debug_page_{page}.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    tweets, next_cursor = parse_page(data)

    new_tweets = []

    for tweet in tweets:

        tweet_id = tweet["id"]

        if tweet_id not in global_seen_ids:
            global_seen_ids.add(tweet_id)
            new_tweets.append(tweet)
            all_tweets.append(tweet)

    print("Tweets on page:", len(tweets))
    print("New tweets:", len(new_tweets))

    if next_cursor:
        print(
            "Next cursor:",
            next_cursor[:50] + "..."
            if len(next_cursor) > 50
            else next_cursor
        )
    else:
        print("Next cursor: None")

    if not next_cursor:
        print("No bottom cursor found.")
        break

    if next_cursor == cursor:
        print("Cursor did not change.")
        break

    cursor = next_cursor
    page += 1

    time.sleep(
        random.uniform(5, 10)
    )


# =========================
# CSV
# =========================

fieldnames = [
    "id",
    "username",
    "name",
    "text",
    "created_at",
    "likes",
    "retweets",
    "replies",
    "quotes",
    "views",
    "url"
]

with open(
    "x_explore.csv",
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(all_tweets)


print("\n=========================")
print("DONE")
print("=========================")

print("Total unique tweets:", len(all_tweets))
print("Saved to x_explore.csv")
