from __future__ import annotations

"""Bluesky posting via AT Protocol."""

import os


BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")


def upload_png(client, png: bytes):
    return client.upload_blob(png)


def image_record(text, alt, blob, created_at):
    from atproto import models
    return models.AppBskyFeedPost.Record(text=text, created_at=created_at,
        embed=models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=alt, image=blob)]))


def create_post(client, text, *, record=None, actor=None):
    if record is None:
        return client.send_post(text=text)
    return client.app.bsky.feed.post.create(repo=actor, record=record)


def post_to_bluesky(text: str) -> dict | None:
    """Post to Bluesky. Returns response dict or None on failure."""
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        print("[bluesky] No credentials configured, skipping post")
        return None

    try:
        from atproto import Client

        client = Client()
        client.login(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
        response = create_post(client, text)
        print(f"[bluesky] Posted: {text[:60]}...")
        return {"uri": str(response.uri), "text": text}
    except Exception as e:
        print(f"[bluesky] Error: {e}")
        return None
