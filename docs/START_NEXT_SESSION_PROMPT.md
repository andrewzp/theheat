# Copy-Paste Prompt for Starting the Next Session

Paste this verbatim into a new chat with a clean context window. It'll
hand you back the project state without making the new session re-read
the full conversation history that just exhausted this one.

---

## PROMPT TO PASTE

```
New session. TheHeat project. Get up to speed fast — read in this order:

1. BRIEFING.md (current state, 1573d15 on main, 522 tests, $25-45/mo)
2. docs/SESSION_BRIEF.md (Apr 24 session summary — what shipped today)
3. docs/NEXT_SESSION.md (action menu, invariants, common commands)
4. docs/DRAFT_CORPUS.md 2026-04-24 section (the corpus that informed
   today's voice work — preserve as longitudinal eval baseline)

Key context, in case you skim:

- Voice engine v2 just shipped (per-category prompts + stock-formula
  rejector). First test of it is the next alerts cycle output.
- Gemini 2.5 Flash → gemini-flash-latest alias. Sonnet 4.6 evaluator
  stays — user explicitly said "do it right for now."
- 35 pending drafts from earlier in session were inventoried in
  DRAFT_CORPUS.md and bulk-rejected. Pending queue cleared.
- 7 of 35 were A/B grade (records, mostly era anchors). 27 fires
  failed. Voice engine v2 directly attacks the failure modes.
- User shared @extremetemps tweets — successful account in our genre
  uses ALL CAPS, "EXTRAORDINARY"/"Mind blowing", multi-station data
  dumps, threading. Our voice rules may be over-engineered for the
  wrong genre. Voice engine v2 partly relaxes; deeper rethink possible.
- User unemployed → cost matters; said "let's do it right for now"
  → keep Sonnet 4.6 evaluator on. EVALUATOR_ENABLED=false is the
  kill switch if circumstances change.

Pinned mid-implementation:
- Multi-station roll-call format for simultaneous_records
- Elevation surfacing in record/anomaly generators (column added to
  cities.csv but not yet used in prompts)
- 13 cities missing elevation values (rate-limited batch retry)

Things explicitly NOT to do (from prior sessions):
- Don't reintroduce human-in-the-loop editorial. Set-and-forget is the
  invariant.
- Don't switch generator off Gemini Flash without explicit permission.
- Don't switch evaluator off Sonnet 4.6. User said no Opus, no Haiku
  for now.
- Don't push to main without confirming the change is what was wanted.
- Don't broaden detection further. Signal side is rich enough; voice
  is the bottleneck.

First move: pull the current pending drafts from the Gist and grade
them like the 2026-04-24 corpus. That tells us whether voice engine
v2 worked. Then pick one of the menu items in docs/NEXT_SESSION.md.

Repo: github.com/andrewzp/theheat. Gist ID for state.json:
06c02c97ffc0d11458687f1ed998d9e5. Be brief in responses — user
prefers action over explanation.
```

---

## What I'd suggest doing first in the new session

After pasting the prompt above, the first concrete action should
probably be:

1. **Pull the pending draft queue.** See the script in
   `docs/NEXT_SESSION.md` "First moves" #1. The next alerts cycle
   under voice engine v2 + `gemini-flash-latest` is the real test —
   no sense planning further voice work without seeing that output.

2. **If drafts look better:** add a new dated section to
   `docs/DRAFT_CORPUS.md` documenting the lift, then pick one of
   menu items A-G in `NEXT_SESSION.md`.

3. **If drafts look the same:** the prompt isn't enough. Time to
   either iterate the prompt harder, kick off the Grok 4 A/B
   (parked in `docs/IDEAS.md`), or start the OS fine-tune lane.
