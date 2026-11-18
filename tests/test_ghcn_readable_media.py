"""Wire approval identity and full native calculation remain separate and exact."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.dashboard_preview.preview import qualified_spec
from src.editorial.revisions import fingerprint
from src.media import gist_temperature_media as media
from src.two_bot.ghcn_readable_warrant import encode_full
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants


@pytest.mark.parametrize(
    "key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")]
)
def test_full_and_readable_inputs_make_identical_native_png_alt_and_science(paired_variants, key):
    full = deepcopy(paired_variants[key]["review_context"]["two_bot"]["bundle"])
    wire = encode_full(full)
    original = deepcopy(wire)
    native = media.prepare_media(full)
    readable = media.prepare_media(wire)
    assert readable["png"] == native["png"]
    assert readable["descriptor"]["alt_text"] == native["descriptor"]["alt_text"]
    assert readable["title"] == native["title"]
    assert readable["descriptor"]["bundle_sha256"] == fingerprint(wire) != fingerprint(full)
    for key in native["descriptor"]:
        if key != "bundle_sha256":
            assert readable["descriptor"][key] == native["descriptor"][key]
    assert media.validate_descriptor(readable["descriptor"], wire) == readable["descriptor"]
    assert qualified_spec(full, include_temperature=True) == qualified_spec(
        wire, include_temperature=True
    )
    assert wire == original
    script = '''
import { readFileSync } from "node:fs"
import { validGistMedia } from "./dashboard/lib/gist-media.js"
if (!validGistMedia(JSON.parse(readFileSync(0, "utf8")))) throw new Error("Saved wire/descriptor binding refused")
'''
    subprocess.run(["node", "--input-type=module", "-e", script],
        input=json.dumps(dict(media_attachment=readable["descriptor"], review_context=dict(two_bot=dict(bundle=wire)))),
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=15, check=True)


@pytest.mark.parametrize("fault", ["alias", "cell", "schema"])
def test_media_refuses_malformed_wire_even_with_new_outer_input_digest(paired_variants, fault):
    full = deepcopy(paired_variants["high", "all_time"]["review_context"]["two_bot"]["bundle"])
    wire = encode_full(full)
    descriptor = media.prepare_media(wire)["descriptor"]
    if fault == "alias":
        wire["historical_context"]["baseline"]["full_baseline_sha256"] = "0" * 64
    elif fault == "cell":
        wire["raw_signal_dump"]["evidence"]["baseline"]["calendar_table"]["rows"][0][4] += 1
    else:
        wire["raw_signal_dump"]["evidence"]["baseline"]["schema_version"] = "theheat-ghcn-unknown"
    descriptor["bundle_sha256"] = fingerprint(wire)
    with pytest.raises(ValueError):
        media.validate_descriptor(descriptor, wire)
    with pytest.raises(ValueError):
        media.prepare_media(wire)


def test_actual_sealed_runtime_renders_readable_png_without_checkout_or_network(
    tmp_path, paired_variants
):
    wire = encode_full(paired_variants["high", "all_time"]["review_context"]["two_bot"]["bundle"])
    path = tmp_path / "invented-wire.json"
    path.write_text(json.dumps(wire))
    archive = Path(__file__).resolve().parents[1] / "dashboard" / "graphic-runtime.zip"
    code = """
import sys, socket, json, hashlib
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
sys.path.insert(0, sys.argv[1])
from src.media.gist_temperature_media import prepare_media
from src.dashboard_preview.preview import qualified_spec
wire = json.load(open(sys.argv[2]))
result = prepare_media(wire)
qualified_spec(wire, include_temperature=True)
sources = [str(getattr(m, "__file__", "")) for k, m in sys.modules.items() if k == "src" or k.startswith("src.")]
assert sources and all(p.startswith(sys.argv[1] + "/") for p in sources), sources
print(json.dumps(dict(png_sha256=hashlib.sha256(result["png"]).hexdigest(), descriptor=result["descriptor"])))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code, str(archive), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    expected = media.prepare_media(wire)
    assert json.loads(completed.stdout) == dict(
        png_sha256=hashlib.sha256(expected["png"]).hexdigest(), descriptor=expected["descriptor"]
    )
