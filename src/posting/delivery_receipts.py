"""Exact local-fixture wire validation and deterministic evidence interpretation."""
from __future__ import annotations

import base64
from email.parser import BytesParser
from email import policy
import hashlib
import re

from src.commands.schema import utc_datetime, utc_text
from src.posting.local_delivery import MAX_REQUEST, MAX_RESPONSE, require, strict_json

ROUTES = {
    ("x", "upload"): "/1.1/media/upload.json",
    ("x", "alt"): "/1.1/media/metadata/create.json",
    ("x", "create"): "/2/tweets",
    ("bluesky", "upload"): "/xrpc/com.atproto.repo.uploadBlob",
    ("bluesky", "create"): "/xrpc/com.atproto.repo.createRecord",
}
HOSTS = {("x", "upload"): "https://upload.twitter.com", ("x", "alt"): "https://upload.twitter.com",
         ("x", "create"): "https://api.twitter.com"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def descriptor(platform, stage, content_type, body):
    require(type(body) is bytes and 0 < len(body) <= MAX_REQUEST, "delivery_request_bound")
    require(type(content_type) is str and len(content_type) <= 256 and "\n" not in content_type
            and "\r" not in content_type, "delivery_content_type_invalid")
    return dict(version=1, method="POST", path=ROUTES[platform, stage], content_type=content_type,
                body_sha256=digest(body), byte_count=len(body))


def verify_request(value, platform, stage, prepared, request, body):
    require(request == descriptor(platform, stage, request["content_type"], body), "delivery_request_descriptor_changed")
    content_type = request["content_type"]
    png = prepared["png"]
    require(digest(png) == value["png_sha256"] and digest(prepared["alt"].encode()) == value["alt_sha256"],
            "delivery_retained_asset_changed")
    if value.get("schema_version") == 2:
        from src.media.platform_description import preflight, profiles
        wire = preflight(value["platform_description"], raw_alt=prepared["alt"].encode("utf-8", errors="strict"),
            png=png, expected_profiles=profiles(value["fixture"]))
        require(wire == prepared["alt"], "delivery_request_content_changed")
    if (platform, stage) == ("x", "upload"):
        require(content_type.startswith("multipart/form-data; boundary="), "delivery_upload_type_invalid")
        message = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        require(message.is_multipart() and not message.defects, "delivery_multipart_invalid")
        parts = list(message.iter_parts())
        require(len(parts) == 1 and not parts[0].defects and parts[0].get_param("name", header="content-disposition") == "media"
                and parts[0].get_filename() == "hot10.png" and parts[0].get_payload(decode=True) == png,
                "delivery_upload_bytes_changed")
        return
    if (platform, stage) == ("bluesky", "upload"):
        # atproto 0.0.72's upload_blob namespace declares input_encoding='*/*'.
        # The retained PNG bytes and returned image/png blob remain exact.
        require(content_type == "*/*" and body == png, "delivery_upload_bytes_changed")
        return
    require(content_type.split(";", 1)[0] == "application/json", "delivery_json_type_invalid")
    data = strict_json(body)
    if platform == "x":
        media_id = prepared["prior"]["upload"]["media_id"]
        expected = ({"media_id":media_id, "alt_text":{"text":prepared["alt"]}} if stage == "alt" else
                    {"text":value["text"], "media":{"media_ids":[media_id]}})
    else:
        from atproto_client.models.blob_ref import BlobRef
        from src.posting.bluesky import image_record
        blob = BlobRef.model_validate(prepared["prior"]["upload"]["blob"])
        record = image_record(value["text"], prepared["alt"], blob, value["created_at"])
        expected = {"repo":value["fixture"]["actor"], "collection":"app.bsky.feed.post", "validate":True,
                    "record":record.model_dump(by_alias=True, exclude_none=True)}
    require(data == expected, "delivery_request_content_changed")
    if value.get("schema_version") == 2 and (platform, stage) in {("x", "alt"), ("bluesky", "create")}:
        actual_alt = data["alt_text"]["text"] if platform == "x" else data["record"]["embed"]["images"][0]["alt"]
        require(actual_alt.encode("utf-8", errors="strict") == prepared["alt"].encode("utf-8", errors="strict")
            and digest(actual_alt.encode("utf-8")) == value["platform_description"]["wire"]["sha256"],
            "delivery_request_content_changed")


def validate_observation(value, saved, observation, response):
    require(type(observation) is dict and set(observation) == {
        "attempt_id", "request_sha256", "source", "reason", "http_status", "complete", "raw_sha256", "recorded_at"},
        "delivery_observation_shape")
    require(type(response) is bytes and len(response) <= MAX_RESPONSE and observation["raw_sha256"] == digest(response),
            "delivery_response_bound")
    require(observation["attempt_id"] == saved["attempt_id"] and observation["request_sha256"] == saved["request_sha256"]
            and saved["configuration_sha256"] == value["configuration_sha256"], "delivery_observation_identity")
    require(observation["source"] in {"response", "reconciliation", "no_call"}
            and observation["reason"] in {"received", "transport_unavailable", "size_exceeded", "time_exceeded", "cleanup_failed", "currentness_refused"}
            and type(observation["complete"]) is bool, "delivery_observation_type")
    status = observation["http_status"]
    require(status is None or type(status) is int and 100 <= status <= 599, "delivery_response_status")
    require(observation["complete"] == (observation["reason"] == "received")
            and (not observation["complete"] or status is not None)
            and (observation["source"] != "no_call" or (not response and status is None and observation["reason"] == "currentness_refused")),
            "delivery_observation_inconsistent")
    require(utc_text(utc_datetime(observation["recorded_at"])) == observation["recorded_at"]
            and utc_datetime(observation["recorded_at"]) >= utc_datetime(saved["recorded_at"]), "delivery_observation_time")


def _cid(value):
    from atproto_core.cid import CID
    require(type(value) is str and 1 <= len(value) <= 256, "delivery_cid_invalid")
    CID.decode(value)
    return value


def _id(value):
    require(type(value) is str and re.fullmatch(r"[0-9]{1,30}", value), "delivery_id_invalid")
    return value


def _positive(value, saved, status, response):
    require(status in (200, 201, 204), "delivery_response_not_successful")
    platform, stage = saved["platform"], saved["stage"]
    if platform == "x" and stage == "alt":
        require(response in (b"", b"{}"), "delivery_metadata_response_invalid")
        return dict(media_id=saved["prior"]["upload"]["media_id"], alt_sha256=value["alt_sha256"])
    data = strict_json(response)
    require(type(data) is dict, "delivery_response_invalid")
    if platform == "x":
        if stage == "upload":
            identity = _id(data["media_id_string"])
            require(type(data["media_id"]) is int and str(data["media_id"]) == identity, "delivery_media_id_mismatch")
            return dict(media_id=identity, png_sha256=value["png_sha256"])
        require(type(data["data"]) is dict and ("text" not in data["data"] or data["data"]["text"] == value["text"]),
                "delivery_response_text_changed")
        return dict(post_id=_id(data["data"]["id"]))
    if stage == "upload":
        from atproto_client.models.blob_ref import BlobRef
        blob = data["blob"]
        BlobRef.model_validate(blob)
        require(set(blob) == {"$type", "ref", "mimeType", "size"} and blob["$type"] == "blob"
                and type(blob["ref"]) is dict and set(blob["ref"]) == {"$link"}
                and blob["mimeType"] == "image/png" and type(blob["size"]) is int and 0 < blob["size"] == value["png_byte_count"] <= 8 * 1024 * 1024,
                "delivery_blob_invalid")
        _cid(blob["ref"]["$link"])
        return dict(blob=blob, png_sha256=value["png_sha256"])
    uri = data["uri"]
    from atproto import models
    models.AppBskyFeedPost.CreateRecordResponse.model_validate(data)
    prefix = "at://" + value["fixture"]["actor"] + "/app.bsky.feed.post/"
    require(type(uri) is str and uri.startswith(prefix) and re.fullmatch(r"[A-Za-z0-9_.:~-]{1,128}", uri[len(prefix):]),
            "delivery_uri_invalid")
    return dict(uri=uri, cid=_cid(data["cid"]))


def interpret(value, saved, observation, response):
    validate_observation(value, saved, observation, response)
    unknown = dict(status="unknown", result=None)
    if observation["source"] == "no_call":
        return dict(status="not_sent", result=None)
    if not observation["complete"]:
        return unknown
    try:
        status = observation["http_status"]
        if observation["source"] == "reconciliation":
            require(status == 200, "delivery_reconciliation_unavailable")
            proof = strict_json(response)
            require(set(proof) == {"kind", "instance_id", "attempt_id", "request_sha256", "status", "body_base64"}
                    and proof["kind"] == "accepted" and proof["instance_id"] == value["fixture"]["instance_id"]
                    and proof["attempt_id"] == saved["attempt_id"] and proof["request_sha256"] == saved["request_sha256"],
                    "delivery_reconciliation_changed")
            response = base64.b64decode(proof["body_base64"], validate=True)
            require(len(response) <= MAX_RESPONSE, "delivery_response_bound")
            status = proof["status"]
        elif status in (400, 401, 403, 429):
            rejection = strict_json(response).get("fixture_rejection")
            if rejection == dict(instance_id=value["fixture"]["instance_id"], attempt_id=saved["attempt_id"],
                                 request_sha256=saved["request_sha256"], accepted=False):
                return dict(status="not_sent", result=None)
        return dict(status="confirmed", result=_positive(value, saved, status, response))
    except Exception:
        # Provider/SDK validation messages can contain response text. Retain only
        # original bounded raw evidence; no guessed ID or exception logging.
        return unknown
