# Start-of-Session Brief

**Written:** 2026-04-24 after voice engine v2 + model upgrade.
**Status going in:** 522 tests green on `main` at `1573d15`. Pending
draft queue clear. The next alerts cycle is the first one running on
`gemini-flash-latest` + voice engine v2 + the geocoder fix + the FRP
floor raise — that output is the eval signal.

This is a 2-minute re-entry doc. If you're back from a break, read
`docs/SESSION_BRIEF.md` first for what just happened.

---

## 60-second state of the world

**Code:**
- Gemini generator now uses `gemini-flash-latest` (Google's alias to
  current best Flash, currently `gemini-3-flash-preview`)
- Voice engine v2 active: per-category prompt addenda, stock-formula
  rejector at parse time, expanded universal prompt with explicit
  bans for the worst template traps
- Fire reverse-geocoder: 70+ named regions, no more "somewhere in Asia"
- FRP floor: 250 MW (was 100 — sub-200 fires don't carry tweets)
- `EVALUATOR_ENABLED` kill switch exists; default on; flip false to
  drop ~$30/mo if cost matters

**Data:**
- 613 cities, 179 countries, with `elevation_m` column. 13 missing
  elevations (rate-limited batch — easy retry).
- 117 historical drafts in state, all rejected.
- Pending queue cleared.
- `docs/DRAFT_CORPUS.md` is the longitudinal voice-quality archive.

**Cost:** ~$25-45/mo (verified). Stale "$60-90" figure was wrong.

## First moves on a new session

### 1. Look at the new draft queue (5 minutes)

Pull pending drafts from the Gist. The first alerts cycle since
voice engine v2 shipped will tell you whether the changes worked. If
fires now lead with named region, no "homes powered" / "no name yet"
formulas, and records lean into era anchors → it worked. If the same
ruts return → the prompt isn't enough and we need stronger
intervention.

```bash
curl -s https://api.github.com/gists/06c02c97ffc0d11458687f1ed998d9e5 \
  | python3 -c "
import json, sys
state = json.loads(json.load(sys.stdin)['files']['state.json']['content'])
for d in [d for d in state.get('drafts', []) if d.get('status') == 'pending']:
    print('---', d.get('type'), '---')
    print(d.get('text', ''))
    print()
"
```

If the new corpus needs grading: append a new dated section to
`docs/DRAFT_CORPUS.md` (oldest stays at the bottom, newest at the top
per the file's pattern).

### 2. Pick one of these next moves

#### A. Multi-station roll-call format (pinned mid-implementation)
The `simultaneous_records` signal triggers on 5+ records same day
but emits a flat summary instead of a per-station list. User wants
this fixed but doesn't want roll-call to be the only output —
build it as a callable format among others. Surface elevation when
the cluster includes high-altitude cities.

Files: `src/data/open_meteo.py` (return per-station data), `src/
voice/generator.py` (new generator function), `src/voice/templates.py`
(roll-call fallback), `src/main.py` (route by cluster shape).

Estimated: 4-6 hours. New tests around 5-10.

#### B. Era-anchor database (Tier 1 from LEVEL_UP_PLAN)
Pre-computed cultural anchors per year for 1995-2025. Generator
gets `[anchors]` for the relevant year as part of the prompt data
instead of asking Gemini to invent one. Ends hallucinated anchors;
gives reliable variety.

Files: new `data/era_anchors.json`, plumb into all
record-type generators in `src/voice/generator.py`.

Estimated: 6-8 hours. One-shot offline curation (use Claude
chat to generate 8+ anchors per year, manual review).

#### C. Revise `docs/LEVEL_UP_PLAN.md`
First-pass plan had analytics as Tier 1; user correctly pointed out
we don't post enough for analytics to mean anything. Rewrite with
quality-side work as Tier 1 (era anchors, regenerate corpus, prompt
iteration) and analytics demoted to Tier 2-3.

Estimated: 30 minutes. Doc-only.

#### D. Fill in the 13 missing elevations
Trivial retry. Run the bulk-fetch script for rows where
`elevation_m` is empty. Spread across smaller batches with longer
delays to avoid the 429.

Estimated: 15 minutes.

#### E. Re-think the voice rules vs @extremetemps
Bigger conversation. The @extremetemps observations from this
session (ALL CAPS openers work, "EXTRAORDINARY" and "Mind blowing"
are tools the genre uses, multi-station data dumps are the format)
suggest some of our rules are too tight. Voice engine v2 partly
addresses this but not fully.

Could be a prompt iteration with explicit "data-ticker genre
permission" — small caps, light editorial heat, density permitted
when warranted.

Estimated: 1-2 hours. Small but high-leverage.

#### F. Visuals
User said maps are "easy to add, hard part is the text." Now that
voice engine v2 ships, this is plausibly closer to ready. But user
also said "we don't want to give up our generator and evaluator
model" — voice quality first.

Defer until voice work proves out.

#### G. Housekeeping
- `rm -rf theheat/theheat/` (stray Conductor worktree duplicate)
- 13 missing elevations (see D)
- LEVEL_UP_PLAN tier reordering (see C)

## Invariants (do not break, preserved across sessions)

- **Utility, not business.** No follower / engagement optimization.
- **Set-and-forget.** No new human-in-the-loop layers.
- **$25-45/mo Anthropic cost is the budget.** Set
  `EVALUATOR_ENABLED=false` to drop it; don't add new paid services
  without asking.
- **Honest framing.** Window must be stated. Open-Meteo = 30 yrs,
  OISST = 44 yrs, GRACE = 24 yrs.
- **Extreme only.** Routine data isn't tweetable.
- **No press-release openers.** Bans enforced by safety pipeline.
- **No meta-commentary.** Voice engine v2 partially relaxed this for
  data-earned editorial heat; still no "THIS IS SERIOUS" /
  "catastrophic" / "life-threatening."
- **Keep Sonnet evaluator on.** User explicitly said "do it right for
  now" — don't switch to Opus or Haiku without permission.
- **Default Gemini stays `gemini-flash-latest`.** Don't pin a
  snapshot unless flipping back from a broken release.

## Common commands

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate

# Full test suite
python -m pytest

# Fetch and grade pending drafts (see "First moves" #1)
# See docs/DRAFT_CORPUS.md for the grading format

# Recent GitHub Actions runs
gh run list --limit 5 --workflow=bot.yml

# Tail a specific run's log for source-level signals
gh run view <ID> --log | grep -iE '\[draft\]|\[alerts\]|\[generator\]'

# Override the generator model without redeploying
gh secret set GEMINI_MODEL  # then paste e.g. gemini-3-flash-preview

# Kill the evaluator (drops cost to ~$0)
gh secret set EVALUATOR_ENABLED  # then type: false
```

## Open thread snapshots

- **Voice quality:** voice engine v2 just shipped. Next corpus is
  the verdict.
- **Models:** Sonnet 4.6 evaluator + `gemini-flash-latest` generator.
  Grok and OS fine-tune are parked in IDEAS.
- **Drafts:** queue cleared. Next alerts cycle generates fresh.
