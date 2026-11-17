"""Current X image wire behind the existing production sender interface.

Tweepy 4.17 supplies OAuth1 signing, but exposes only legacy media methods. This
adapter implements the documented v2 JSON image/metadata endpoints with the same
user token. Admission, durable intent and retry decisions remain in the caller.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from http import HTTPStatus
import json
import re

import requests
import tweepy

MAX_PNG = 5 * 1024 * 1024
MAX_RESPONSE = 65536
_ID = re.compile(r"[1-9][0-9]{0,18}\Z", re.ASCII)


def _invalid():
    raise tweepy.TweepyException("x_media_response_invalid")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _invalid()
        value[key] = item
    return value


def _constant(_value):
    _invalid()


@dataclass(frozen=True)
class UploadedMedia:
    media_id: str


class XMediaAPI:
    def __init__(self, consumer_key, consumer_secret, access_token, access_secret):
        self._auth = tweepy.OAuth1UserHandler(
            consumer_key, consumer_secret, access_token, access_secret).apply_auth()

    @staticmethod
    def validate_png(png):
        if type(png) is not bytes or not 8 < len(png) <= MAX_PNG or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise tweepy.TweepyException("x_media_png_invalid")

    @staticmethod
    def validate_metadata(media_id, alt_text):
        if (type(media_id) is not str or not _ID.fullmatch(media_id)
                or type(alt_text) is not str or not 0 < len(alt_text) <= 1000):
            raise tweepy.TweepyException("x_media_metadata_invalid")
        try:
            alt_text.encode("utf-8", errors="strict")
        except UnicodeError:
            raise tweepy.TweepyException("x_media_metadata_invalid") from None

    def _request(self, route, payload):
        if route not in ("upload", "metadata"):
            raise tweepy.TweepyException("x_media_route_invalid")
        try:
            with requests.Session() as session:
                session.trust_env = False
                # Requests' default adapters have zero retries. No server-selected
                # redirect or environment proxy may move the signed request.
                with session.post("https://api.x.com/2/media/" + route, json=payload,
                                  auth=self._auth, timeout=(5, 5), allow_redirects=False,
                                  stream=True) as response:
                    status = response.status_code
                    if status not in (200, 201):
                        # HTTP exception messages must not contain provider prose.
                        safe = requests.Response()
                        safe.status_code = status
                        safe.reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "HTTP error"
                        error = (tweepy.Unauthorized if status == 401 else
                                 tweepy.TooManyRequests if status == 429 else tweepy.HTTPException)
                        raise error(safe, response_json={})
                    raw = bytearray()
                    for chunk in response.iter_content(chunk_size=16384):
                        if len(raw) + len(chunk) > MAX_RESPONSE:
                            _invalid()
                        raw.extend(chunk)
                    data = json.loads(raw.decode("utf-8", errors="strict"),
                                      object_pairs_hook=_object, parse_constant=_constant)
                    if (type(data) is not dict or data.get("errors", []) != []
                            or type(data.get("data")) is not dict):
                        _invalid()
                    return data["data"]
        except requests.RequestException:
            raise tweepy.TweepyException("x_media_transport_unknown") from None
        except (ValueError, UnicodeError, TypeError):
            raise tweepy.TweepyException("x_media_response_invalid") from None

    def media_upload(self, *, filename, file):
        png = file.read(MAX_PNG + 1)
        self.validate_png(png)
        data = self._request("upload", {
            "media": base64.b64encode(png).decode("ascii"), "media_category": "tweet_image"})
        identity = data.get("id")
        if type(identity) is not str or not _ID.fullmatch(identity):
            _invalid()
        if "size" in data and (type(data["size"]) is not int or data["size"] != len(png)):
            _invalid()
        if "expires_after_secs" in data and (type(data["expires_after_secs"]) is not int or data["expires_after_secs"] <= 0):
            _invalid()
        if "processing_info" in data and (type(data["processing_info"]) is not dict
                or data["processing_info"].get("state") != "succeeded"
                or data["processing_info"].get("error") is not None):
            # No implicit polling or second upload after an ambiguous response.
            _invalid()
        return UploadedMedia(identity)

    def create_media_metadata(self, media_id, alt_text):
        self.validate_metadata(media_id, alt_text)
        data = self._request("metadata", {"id": media_id, "metadata": {"alt_text": {"text": alt_text}}})
        if data.get("id") != media_id:
            _invalid()
        return None
