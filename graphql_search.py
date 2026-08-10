import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import requests


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

SEARCH_OPERATION_IDS = [
    "PusO6nN_nUSAsfJktZJd9w",
    "-TFXKoMnMTKdEXcCn-eahw",
    "nK1dw4oV3k4w5TdtcAdSww",
    "yiE17ccAAu3qwM34bPYZkQ",
]

SEARCH_URLS = [
    os.getenv("X_SEARCH_GRAPHQL_URL"),
    *(
        f"https://x.com/i/api/graphql/{operation_id}/SearchTimeline"
        for operation_id in SEARCH_OPERATION_IDS
    ),
]
SEARCH_URLS = list(dict.fromkeys(url for url in SEARCH_URLS if url))

AUTH_TOKEN = os.getenv("X_AUTH_TOKEN", "")
CT0 = os.getenv("X_CT0", "")
BEARER = os.getenv("X_BEARER", "")

DEFAULT_KEYWORDS = [
    "india","ravi kishan meme",
]

FIELD_TOGGLES = {
    "withPayments": False,
    "withAuxiliaryUserLabels": False,
    "withArticleRichContentState": False,
    "withArticlePlainText": False,
    "withArticleSummaryText": False,
    "withArticleVoiceOver": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
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


def build_headers():
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "authorization": f"Bearer {BEARER}",
        "x-csrf-token": CT0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "cookie": f"auth_token={AUTH_TOKEN}; ct0={CT0}",
        "referer": "https://x.com/search",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }


def fetch_search_page(query, cursor="", count=20, product="Latest"):
    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": product,
        "withGrokTranslatedBio": True,
        "withQuickPromoteEligibilityTweetFields": False,
    }

    if cursor:
        variables["cursor"] = cursor

    payload = {
        "variables": variables,
        "features": FEATURES,
        "fieldToggles": FIELD_TOGGLES,
    }

    last_404 = None

    for index, url in enumerate(SEARCH_URLS, start=1):
        print(f"Endpoint {index}/{len(SEARCH_URLS)}:", url.rsplit("/", 2)[1])

        response = requests.post(
            url,
            headers=build_headers(),
            json=payload,
            timeout=30,
        )

        print("HTTP:", response.status_code)

        if response.status_code == 404:
            last_404 = response
            continue

        if response.status_code != 200:
            print(response.text[:2000])

        response.raise_for_status()

        return response.json()

    if last_404 is not None:
        raise RuntimeError(
            "All configured SearchTimeline operation ids returned HTTP 404. "
            "Capture a fresh SearchTimeline request URL from X and set "
            "X_SEARCH_GRAPHQL_URL in .env."
        )

    raise RuntimeError("No SearchTimeline endpoint URLs are configured.")


# =========================
# TWEET EXTRACTION
# =========================

def make_media_urls(legacy):
    media_items = legacy.get("extended_entities", {}).get("media", [])
    if not media_items:
        media_items = legacy.get("entities", {}).get("media", [])

    urls = []

    for item in media_items:
        media_url = item.get("media_url_https") or item.get("media_url")
        expanded_url = item.get("expanded_url")

        if media_url:
            urls.append(media_url)
        elif expanded_url:
            urls.append(expanded_url)

    return "|".join(urls)


def make_tweet(result, keyword):
    """
    Converts an X tweet result object into a flat dictionary.
    """

    if not isinstance(result, dict):
        return None

    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy")

    if not legacy:
        return None

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

    views = (
        result
        .get("views", {})
        .get("count", "")
    )

    return {
        "keyword": keyword,
        "id": tweet_id,
        "username": username,
        "name": name,
        "text": legacy.get("full_text", ""),
        "created_at": legacy.get("created_at", ""),
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "quotes": legacy.get("quote_count", 0),
        "bookmarks": legacy.get("bookmark_count", 0),
        "views": views,
        "media": make_media_urls(legacy),
        "url": (
            f"https://x.com/{username}/status/{tweet_id}"
            if username and tweet_id
            else ""
        ),
    }


def recursive_find_tweets(obj, keyword, tweets, seen_ids):
    """
    Recursively searches the entire response for tweet result objects.
    """

    if isinstance(obj, dict):
        if "tweet_results" in obj:
            result = (
                obj.get("tweet_results", {})
                .get("result", {})
            )

            tweet = make_tweet(result, keyword)

            if tweet:
                tweet_id = tweet["id"]

                if tweet_id and tweet_id not in seen_ids:
                    seen_ids.add(tweet_id)
                    tweets.append(tweet)

        if obj.get("__typename") in (
            "Tweet",
            "TweetWithVisibilityResults",
        ):
            tweet = make_tweet(obj, keyword)

            if tweet:
                tweet_id = tweet["id"]

                if tweet_id and tweet_id not in seen_ids:
                    seen_ids.add(tweet_id)
                    tweets.append(tweet)

        for value in obj.values():
            recursive_find_tweets(value, keyword, tweets, seen_ids)

    elif isinstance(obj, list):
        for item in obj:
            recursive_find_tweets(item, keyword, tweets, seen_ids)


# =========================
# CURSOR EXTRACTION
# =========================

def recursive_find_bottom_cursor(obj):
    """
    Finds Bottom cursor anywhere in the SearchTimeline response.
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

def parse_page(data, keyword):
    tweets = []
    seen_ids = set()

    recursive_find_tweets(
        data,
        keyword,
        tweets,
        seen_ids,
    )

    cursor = recursive_find_bottom_cursor(data)

    return tweets, cursor


# =========================
# KEYWORDS
# =========================

def load_keywords(args):
    keywords = []

    for value in args.keywords:
        if value.strip():
            keywords.append(value.strip())

    if args.keywords_file:
        path = Path(args.keywords_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()

            if value and not value.startswith("#"):
                keywords.append(value)

    if args.query:
        keywords.append(args.query.strip())

    if not keywords:
        keywords.extend(DEFAULT_KEYWORDS)

    return list(dict.fromkeys(keywords))


# =========================
# MAIN
# =========================

def run(args):
    require_auth()

    keywords = load_keywords(args)

    debug_dir = Path(args.debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)

    all_tweets = []
    global_seen_ids = set()

    for keyword_index, keyword in enumerate(keywords, start=1):
        cursor = ""
        page = 1

        print("\n=========================")
        print("Searching:", keyword)
        print("=========================")

        while page <= args.max_pages:
            print(f"\nFetching search page {page}...")

            data = fetch_search_page(
                keyword,
                cursor=cursor,
                count=args.count,
                product=args.product,
            )

            safe_keyword = "".join(
                char if char.isalnum() else "_"
                for char in keyword
            ).strip("_")[:60] or "query"

            debug_path = (
                debug_dir
                / f"search_{keyword_index:02d}_{safe_keyword}_page_{page}.json"
            )

            with debug_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            tweets, next_cursor = parse_page(data, keyword)

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
                    else next_cursor,
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

            time.sleep(random.uniform(args.min_sleep, args.max_sleep))

    fieldnames = [
        "keyword",
        "id",
        "username",
        "name",
        "text",
        "created_at",
        "likes",
        "retweets",
        "replies",
        "quotes",
        "bookmarks",
        "views",
        "media",
        "url",
    ]

    with open(
        args.output,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_tweets)

    print("\n=========================")
    print("DONE")
    print("=========================")
    print("Total unique tweets:", len(all_tweets))
    print("Saved to:", args.output)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Search X with the web GraphQL SearchTimeline endpoint. "
            "With no keywords, uses DEFAULT_KEYWORDS in this file."
        )
    )
    parser.add_argument(
        "keywords",
        nargs="*",
        help="Keyword/search strings. Quote multi-word queries.",
    )
    parser.add_argument(
        "--query",
        help="Single advanced X search query, for example: \"india lang:en\".",
    )
    parser.add_argument(
        "--keywords-file",
        help="Text file with one keyword/search query per line.",
    )
    parser.add_argument(
        "--product",
        default="Top",
        choices=["Top", "Latest", "People", "Photos", "Videos"],
        help="Search product/tab to request.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Requested result count per page.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum pages to fetch per keyword.",
    )
    parser.add_argument(
        "--output",
        default="x_search_results.csv",
        help="CSV output path.",
    )
    parser.add_argument(
        "--debug-dir",
        default="debug_search",
        help="Directory for raw JSON responses.",
    )
    parser.add_argument(
        "--min-sleep",
        type=float,
        default=5.0,
        help="Minimum seconds to sleep between pages.",
    )
    parser.add_argument(
        "--max-sleep",
        type=float,
        default=10.0,
        help="Maximum seconds to sleep between pages.",
    )

    args = parser.parse_args(argv)

    if args.count < 1 or args.count > 50:
        parser.error("--count must be between 1 and 50.")

    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1.")

    if args.min_sleep < 0 or args.max_sleep < 0:
        parser.error("--min-sleep and --max-sleep cannot be negative.")

    if args.min_sleep > args.max_sleep:
        parser.error("--min-sleep cannot be greater than --max-sleep.")

    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        run(args)
    except (RuntimeError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
