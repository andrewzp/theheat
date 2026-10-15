"""Invented v1 metadata rows for passive compatibility, never a legacy sender.

The current editor produces a real v1 local review/check/park transition without
delivery configured. The owner-only fixture adds the old delivery reference to
that exact result/event and seeds the old immutable request/barrier shape. No
production gate is patched, no scientific package is fabricated or shortened,
and no platform POST is sent. These rows model historical obligations only.
"""
from src.commands import postgres_delivery as delivery, postgres_media as media
from src.commands.schema import utc_text
from src.editorial.revisions import fingerprint
from src.posting import delivery_receipts as receipts
from src.storage import postgres_projection as p
from tests import test_postgres_editor_media as editor


def seed_intent(case, params, command, result, config, configuration_sha256):
    state = case["store"].read()[1]
    draft = next(d for d in state["drafts"] if d["id"] == case["draft_id"])
    binding = draft["approval_binding"]
    assert binding["schema_version"] == 1 and draft["media_review_binding"]["schema_version"] == 1
    with p._driver().connect(**dict(params, autocommit=False)) as c:
        package = media.read(c, binding["media"]["proposal_sha256"], "local")
        value = dict(schema_version=1, scope=delivery.SCOPE, publication_approved=False,
            intent_id=binding["publish_intent_id"], command_id=command.command_id,
            draft_id=draft["id"], event_id=draft["event_id"], text=draft["text"], approval_binding=binding,
            fixture=config, configuration_sha256=configuration_sha256, proposal_sha256=binding["media"]["proposal_sha256"],
            package=package["receipt"], png_sha256=p._sha(package["assets"]["preview.png"]),
            png_byte_count=len(package["assets"]["preview.png"]), alt_sha256=p._sha(package["assets"]["alt.txt"]),
            created_at=utc_text(editor.AT))
        old_result = dict(result, delivery=delivery.references(value))
        raw = p._canonical(old_result)
        # Owner fixture only; production append-only guards remain installed and
        # are verified unchanged by the authority on subsequent current reads.
        c.execute("SET LOCAL session_replication_role=replica")
        c.execute("UPDATE theheat_commands.results SET result_bytes=%s,digest=%s WHERE command_id=%s", (raw,p._sha(raw),command.command_id))
        c.execute("UPDATE theheat_commands.events SET data_bytes=%s,digest=%s WHERE command_id=%s AND event='completed'", (raw,p._sha(raw),command.command_id))
        digest = delivery.record(c, value)
        c.execute("INSERT INTO theheat_delivery.intents VALUES(%s,%s,%s,%s,%s,%s)",
            (value["intent_id"],command.command_id,draft["id"],draft["event_id"],value["proposal_sha256"],digest))
        for platform in delivery.STAGES:
            c.execute("INSERT INTO theheat_delivery.work_items VALUES(%s,%s,%s)", (delivery.work(value,platform),value["intent_id"],platform))
    return value, package


def seed_attempt(params, value, package, *, stage="upload", prior=None):
    """Exact requests serializer bytes, with no transport or fake check result."""
    import requests
    from datetime import timedelta
    if stage == "upload":
        request = requests.Request("POST", "https://upload.twitter.com/1.1/media/upload.json",
            files={"media":("hot10.png",package["assets"]["preview.png"],"image/png")}).prepare()
    else:
        request = requests.Request("POST", "https://api.twitter.com/2/tweets",
            json=dict(text=value["text"],media=dict(media_ids=[prior["upload"]["media_id"]]))).prepare()
    body = request.body
    descriptor = receipts.descriptor("x",stage,request.headers["Content-Type"],body)
    receipts.verify_request(value,"x",stage,dict(png=package["assets"]["preview.png"],alt=package["assets"]["alt.txt"].decode(),prior=prior or {}),descriptor,body)
    with p._driver().connect(**dict(params,autocommit=False)) as c:
        delivery.artifact(c,body)
        request_sha = delivery.record(c,descriptor)
        work = delivery.work(value,"x")
        expires = utc_text(editor.AT+timedelta(seconds=30))
        c.execute("INSERT INTO theheat_delivery.leases VALUES(%s,%s,1,%s,%s,%s)", (work,stage,"historical-fixture",utc_text(editor.AT),expires))
        saved = dict(intent_id=value["intent_id"],platform="x",stage=stage,owner="historical-fixture",fence=1,
            expires_at=expires,request_sha256=request_sha,configuration_sha256=value["configuration_sha256"],recorded_at=utc_text(editor.AT),prior=prior or {})
        saved["attempt_id"] = fingerprint(saved)
        binding_sha = delivery.record(c,saved)
        c.execute("INSERT INTO theheat_delivery.attempts VALUES(%s,%s,%s,1,%s,%s)", (saved["attempt_id"],work,stage,binding_sha,request_sha))
    return saved, descriptor, body
