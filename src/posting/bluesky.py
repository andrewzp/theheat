from __future__ import annotations

"""Bluesky posting via AT Protocol."""

import os
from datetime import datetime, timezone

from atproto import Client


BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")


def post_to_bluesky(text: str) -> dict | None:
    """Post to Bluesky. Returns response dict or None on failure."""
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        print("[bluesky] No credentials configured, skipping post")
        return None

    try:
        client = Client()
        client.login(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
        response = client.send_post(text=text)
        print(f"[bluesky] Posted: {text[:60]}...")
        return {"uri": str(response.uri), "text": text}
    except Exception as e:
        print(f"[bluesky] Error: {e}")
        return None
