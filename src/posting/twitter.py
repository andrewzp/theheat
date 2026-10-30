from __future__ import annotations

"""X/Twitter posting via tweepy."""

import os
from io import BytesIO

import tweepy

API_KEY = os.environ.get("TWITTER_API_KEY", "")
API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "")


def _get_client() -> tweepy.Client | None:
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        return None
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
    )


def _get_upload_api() -> tweepy.API | None:
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        return None
    auth = tweepy.OAuth1UserHandler(
        API_KEY,
        API_SECRET,
        ACCESS_TOKEN,
        ACCESS_SECRET,
    )
    return tweepy.API(auth)


def _declared(send, stage=None):
    """Each X SDK phase consumes the declared platform stage before egress."""
    from src.posting import outbox_outcome
    from src.two_bot.call_inventory import consume
    ticket = consume("x_publish", provider="x")
    entry = outbox_outcome.begin(stage) if stage else None
    try:
        response = send()
    except BaseException as exc:
        outbox_outcome.finish(entry, exc)
        ticket.settle("unknown")
        raise
    outbox_outcome.finish(entry)
    ticket.settle("returned")
    return response


def upload_png(api, png: bytes, **options):
    """One SDK phase; authorization and durable effects belong to its caller."""
    return _declared(lambda: api.media_upload(filename="hot10.png", file=BytesIO(png), **options), "upload")


def set_alt_text(api, media_id: str, alt_text: str, **options):
    return _declared(lambda: api.create_media_metadata(media_id, alt_text, **options), "alt")


def create_post(client, text: str, media_ids=None, **options):
    if media_ids is not None:
        options["media_ids"] = media_ids
    return _declared(lambda: client.create_tweet(text=text, **options), "create")


def post_tweet(
    text: str,
    media_png: bytes | None = None,
    alt_text: str | None = None,
) -> dict | None:
    """Post a tweet. Returns response dict, rate-limit sentinel, or None on failure.

    Returns ``{"error": "rate_limited"}`` on 429 so callers can distinguish
    transient rate limits from permanent failures.
    """
    from src.posting.outbox_outcome import refuse_before_egress
    client = _get_client()
    if not client:
        print("[twitter] No credentials configured, skipping post")
        refuse_before_egress("credentials_unavailable")
        return None

    try:
        media_ids = None
        if media_png is not None:
            upload_api = _get_upload_api()
            if upload_api is None:
                print("[twitter] No upload API credentials configured, skipping post")
                refuse_before_egress("upload_credentials_unavailable")
                return None
            media = upload_png(upload_api, media_png)
            media_id = str(media.media_id)
            if alt_text:
                set_alt_text(upload_api, media_id, alt_text)
            media_ids = [media_id]

        response = create_post(client, text, media_ids)
        tweet_id = response.data["id"]
        print(f"[twitter] Posted tweet {tweet_id}: {text[:60]}...")
        return {"id": tweet_id, "text": text}
    except tweepy.TooManyRequests:
        print("[twitter] Rate limited (429), tweet will stay in drafts for retry")
        return {"error": "rate_limited"}
    except tweepy.Unauthorized:
        print("[twitter] Auth failure (401)")
        return None
    except tweepy.TweepyException as e:
        print(f"[twitter] Error: {e}")
        return None
