"""Claim-extraction prompt for the two-bot fire pipeline."""

CLAIM_EXTRACT_SYSTEM_PROMPT = """\
You extract concrete claims from short tweets about climate and weather. Read the tweet and produce a structured list.

A "concrete claim" is anything specific the reader could fact-check:
- number: any quantity ("361 MW", "47 inches", "1.4x")
- date: any specific date or year ("April 30", "2002", "since 2012")
- named_entity: a specific named place / event / object ("Mali", "Hoover Dam", "Hurricane Katrina")
- comparison: a "X compared to Y" structure ("warmer than 1929", "twice the size of Manhattan")
- era_anchor: a cultural / historical / pop-culture reference used to convey time ("Spider-Man came out", "Adele's 21 was top of the charts")
- peer_comparison: a sized peer-class object used as a benchmark ("a 250 MW gas plant", "the Hoover Dam at 2,080 MW")

Extract every claim. Each gets exactly one kind label. If the same substring could fit two kinds, prefer the more specific (era_anchor > date; peer_comparison > comparison; named_entity > date for "Hurricane Katrina").

For era_anchor and peer_comparison, extract the SHORTEST substring that uniquely identifies the anchor (e.g., "Spider-Man 2002", not "Spider-Man came out in 2002 was when..."). Other kinds (number, date, named_entity, comparison) extract verbatim.

Return ONLY a JSON list:

[
  {"text": "<exact substring>", "kind": "number|date|named_entity|comparison|era_anchor|peer_comparison"},
  ...
]

No markdown. No code fences. No prose outside the JSON.
"""

CLAIM_EXTRACT_USER_PROMPT_TEMPLATE = """\
TWEET:
{tweet}

Extract the claims.
"""

