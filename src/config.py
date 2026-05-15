"""Central model config for @theheat.

One place to read or override the model defaults used by the voice
generator and the two-bot pipeline. Each caller still keeps its own
specific env-var override (``THEHEAT_FACT_CHECK_MODEL``,
``THEHEAT_CLAIM_EXTRACT_MODEL``, ``THEHEAT_WRITER_MODEL``,
``GEMINI_MODEL``) for surgical changes; this module just provides the
fallback default when those are unset.

Background: prior to 2026-05-03 each module hardcoded its own default,
which led to the voice generator silently rolling onto
``gemini-flash-latest`` (a preview alias pointing at Gemini 3 Flash)
while the two-bot files stayed pinned to the stable ``gemini-2.5-flash``.
The mismatch caused indefinite hangs in production. Centralizing the
defaults here makes future model decisions a one-line change.
"""

from __future__ import annotations

import os

# Cheap fast model used for structured-output tasks (fact-checking,
# claim extraction) and for voice-candidate generation. Pinned to the
# stable Flash snapshot — *not* ``gemini-flash-latest`` — because that
# alias quietly rolls to preview models (currently Gemini 3 Flash
# Preview) which have higher latency variance under our voice-gen
# workload (12K-char prompts asking for 4 candidates).
CHEAP_MODEL = os.environ.get("THEHEAT_CHEAP_MODEL", "gemini-2.5-flash")

# Editorial model used by the two-bot writer and (currently) the
# voice-generator evaluator pass. Sonnet is the right tier for the
# creative judgment work; Haiku/Flash struggle with theheat's banned-
# phrase discipline and tone constraints.
WRITER_MODEL = os.environ.get("THEHEAT_WRITER_MODEL", "claude-sonnet-4-6")

# Second-pass editorial critic — runs after fact_check passes, the final
# gate before a draft enters the human-approval queue. Cross-family with
# the Sonnet writer (Gemini 2.5 Pro) for taste diversity: the critic's
# job is to catch the writer's blind spots, especially template
# convergence across same-cron drafts. Per the 2026-05-15 handoff:
# "Start with Gemini 2.5 Pro as the v1 model (cross-family vs Sonnet
# writer, no new SDK wiring beyond the existing google-genai)."
# NEVER Flash here — Flash has no taste for editorial gating (see
# feedback_theheat_flash_no_taste.md).
CRITIC_MODEL = os.environ.get("THEHEAT_CRITIC_MODEL", "gemini-2.5-pro")
