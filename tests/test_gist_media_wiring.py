"""Configuration hand-off for the shared media store (no secret, no dispatch, no job change).

The manual sender run receives only the read-only selection; opt-in CRW retention
receives the insert-only selection only outside manual_tweet runs and only when the
explicit flag is "1". One exact driver pin is shared by the bot, test and dashboard
profiles; the preview function deploys the locked profile.
"""
import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
PIN = "psycopg[binary]==3.3.6"


def _bot_env():
    bot = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(s for job in bot["jobs"].values() for s in job.get("steps", []) if s.get("name") == "Run bot")
    return step["env"]


def test_sender_runs_are_read_only_and_retention_runs_insert_only():
    env = _bot_env()
    sender = "steps.mode.outputs.mode == 'manual_tweet'"
    collector = "steps.mode.outputs.mode != 'manual_tweet'"
    assert env["THEHEAT_MEDIA_STORE"] == f"${{{{ {sender} && vars.THEHEAT_MEDIA_STORE || '' }}}}"
    assert env["THEHEAT_MEDIA_STORE_DSN"] == f"${{{{ {sender} && secrets.THEHEAT_MEDIA_STORE_DSN || '' }}}}"
    assert env["THEHEAT_CRW_PACKET_RETENTION"] == f"${{{{ {collector} && vars.THEHEAT_CRW_PACKET_RETENTION || '0' }}}}"
    for name, source in (("THEHEAT_MEDIA_WRITER_STORE", "vars.THEHEAT_MEDIA_WRITER_STORE"),
                         ("THEHEAT_MEDIA_WRITER_DSN", "secrets.THEHEAT_MEDIA_WRITER_DSN")):
        assert env[name] == (f"${{{{ {collector} && vars.THEHEAT_CRW_PACKET_RETENTION == '1' && {source} || '' }}}}")
    # No other step or workflow receives a media credential.
    text = "\n".join(p.read_text() for p in (ROOT / ".github/workflows").glob("*.yml"))
    assert len(re.findall(r"secrets\.THEHEAT_MEDIA_(?:STORE|WRITER)_DSN", text)) == 2


def test_one_exact_driver_pin_everywhere_and_the_preview_deploys_the_lock():
    for path in ("requirements.txt", "requirements-postgres.txt"):
        assert PIN in (ROOT / path).read_text().splitlines()
    assert f'"{PIN}",' in (ROOT / "dashboard/pyproject.toml").read_text()
    lock = (ROOT / "dashboard/uv.lock").read_text()
    assert 'name = "psycopg"\nversion = "3.3.6"' in lock and 'name = "psycopg-binary"\nversion = "3.3.6"' in lock
    functions = json.loads((ROOT / "dashboard/vercel.json").read_text())["functions"]
    assert all("pyproject.toml" in spec["includeFiles"] and "uv.lock" in spec["includeFiles"] for spec in functions.values())
