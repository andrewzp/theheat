#!/usr/bin/env python3
"""Generate the dashboard's advisory source inventory from local code only."""

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src.data.source_registry import registry_document  # noqa: E402

OUTPUT = REPO / "dashboard/lib/source-registry.json"


def render():
    return json.dumps(registry_document(REPO), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    rendered = render()
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            raise SystemExit("Source inventory is stale; run scripts/gen_source_registry.py")
    else:
        OUTPUT.write_text(rendered)
