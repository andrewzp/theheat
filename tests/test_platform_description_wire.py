"""Actual SDK serialization, invented loopback only; no scientific qualification."""
import json
import time

import pytest

from src.commands.schema import canonical_json
from src.posting import delivery_transport as transport, delivery_receipts as receipts
from tests.local_delivery_helpers import fixture_server, value, cid
from tests.test_local_delivery_transport import PNG, TEXT


@pytest.mark.parametrize("alt", ["Complete description.\n", "Complete description.\r\n",
    "Literal \\n description.\n", "😀 e\u0301 é 日本語.\n", "a" * 999 + "\n"],
    ids=["lf", "crlf", "literal-backslash-n", "unicode", "1000-ascii"])
def test_actual_sdk_decoded_fields_are_exact_approved_utf8(alt):
    raw = alt.encode("utf-8")
    with fixture_server(PNG, TEXT) as (config, trace, accepted):
        source = value(config, PNG, alt=alt)
        assert source["platform_description"]["wire"]["sha256"] == receipts.digest(raw)
        for platform, stage, prior in (
            ("x", "alt", {"upload":{"media_id":"100"}}),
            ("bluesky", "create", {"upload":{"blob":{"$type":"blob", "ref":{"$link":cid(PNG)}, "mimeType":"image/png", "size":len(PNG)}}}),
        ):
            retained = []

            def begin(request, body):
                return dict(dispatch_granted=True, binding=dict(attempt_id=receipts.digest(body),
                    request_sha256=receipts.digest(canonical_json(request).encode()),
                    configuration_sha256=source["configuration_sha256"], platform=platform,
                    stage=stage, prior=prior, recorded_at=source["created_at"]))

            def observe(saved, response, source_kind="response"):
                retained.append(response)

            result = transport.execute(source, platform, stage,
                dict(png=PNG, alt=alt, prior=prior, eligibility_deadline=time.monotonic()+30),
                begin=begin, observe=observe, check=lambda _:None)
            assert result["sdk_completed"] and len(retained) == 1, result
            body = json.loads(trace[-1]["body"])
            decoded = body["alt_text"]["text"] if platform == "x" else body["record"]["embed"]["images"][0]["alt"]
            assert decoded.encode("utf-8") == raw
            assert receipts.digest(decoded.encode("utf-8")) == source["platform_description"]["wire"]["sha256"]
        assert len(trace) == len(accepted) == 2
