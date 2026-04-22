# Start-of-Session Brief

**Written:** 2026-04-22 after the 4-lane merge + Codex cleanup.
**Status going in:** Everything shipped and green. No open PRs. No open
bugs that Codex flagged. 501 tests passing on `main` at `0be88fc`.

If you're coming back after a break, read this first. It's a 2-minute
re-entry doc.

---

## 60-second state of the world

- Four new detection lanes merged during Apr 19–22: Ocean SST (marine
  heatwave streaks), GRACE-FO ice mass, NIFC fire footprint, Fire×
  Drought×Heat cross-source synthesis.
- FIRMS letter-confidence bug fixed — wildfire detection was silently
  returning zero all day for some period. Now working.
- NWS widened to 9 Extreme-tier event types (added Blizzard, Ice Storm,
  Extreme Cold, Extreme Heat Warnings).
- City list expanded 257 → 613, 179 countries.
- CO2 weekly pathway dead (routine noise). NOAA confirmation pathway
  dead (redundant news). Replaced with: country-level records,
  cross-source synthesis.
- Four Codex-found bugs fixed before stop: state merge for synthesis,
  sqlite round-trip for lane keys, synthesis scorer anomaly vs. absolute
  temp, per-cycle cap orphaning event IDs.

## Where to pick up (menu — pick one)

### A. Voice engine upgrade (highest leverage for tweet quality)
User's last observation: *"they are ok. neither is going to go viral
by any stretch."* The pipeline is thick with signal types now; the
ceiling is voice quality. See `docs/IDEAS.md` → "Voice engine upgrade"
for four candidate interventions. The simplest ship: **"lead with the
stake" rewrite pass** — reorder tweets so the first 5–7 words carry
the surprise, not the place+number.

### B. Fire reverse-geocoder fix (fastest concrete win)
FIRMS now produces fire drafts globally, but ~4 of 13 in the current
queue admit "somewhere in Asia" / "location unknown" because
`firms.py::reverse_geocode_simple` only returns continent-level
labels. A static bounding-box dict (mirrors the Lane 4 US-state
solution) is ~2 hours of work. See `docs/IDEAS.md` → "Fire
reverse-geocoder regional precision."

### C. Watch what landed in production
No changes — just check the draft queue at
https://dashboard-phi-beryl-65.vercel.app and see whether the new
signal types (marine heatwave, ice mass, fire footprint, synthesis)
have fired yet. Some are condition-gated — ice mass is Mondays-only,
synthesis needs D4 drought + fire + heat in the same US state — so
absence isn't a bug, it's just waiting on conditions.

### D. Housekeeping
Small items:
- `rm -rf theheat/theheat/` — stray Conductor worktree duplicate
  subdirectory. Untracked, safe to delete. Fixes
  `ImportPathMismatchError` on repo-root pytest.
- The `_prune_weakest_cycle_drafts` source-key map in `main.py` is
  enumerative — every new signal type needs an entry. Acceptable
  today, but worth a refactor to derive the mapping from a single
  source of truth if we add more lanes.

### E. Additional synthesis rules
The synthesis scaffolding from Lane 4 supports more rules. The two
candidate follow-ups:
- **Marine heatwave × coastal heat dome** — waiting for OISST
  to have fired enough times in production to tune the rule against
  real data.
- **Hurricane × storm surge × river flood** — holds until hurricane
  season (June–November) so the rule can be observed firing in
  production before we trust it.

### F. Dashboard work
Several dashboard-side things are loose:
- Dashboard may be behind latest `main` on Vercel — verify deploys.
- The `drafts` API doesn't yet expose country/tweet_date/city
  columns on the new synthesis / country / ice_mass / marine_heatwave
  drafts the way it exposes them for per-city records. Low-priority
  polish.

---

## Invariants to respect (from prior sessions)

- **Utility, not business.** No follower/engagement optimization.
- **Set-and-forget.** Cron + gist only. No new human-in-the-loop
  editorial layers beyond the dashboard.
- **$0 recurring** except the ~$60–90/mo Anthropic for Sonnet
  evaluator. No new paid services without asking.
- **Honest framing.** Archive window (30 yrs for Open-Meteo, 44 yrs
  for OISST, 24 yrs for GRACE) must be stated. Never "hottest ever."
- **Extreme only.** Routine data isn't tweetable. CO2 weekly and
  NOAA confirmations were killed for being drip-drip-drip.
- **No press-release openers.** Safety pipeline bans NOAA/NWS/GDACS
  at the start of a tweet.
- **No meta-commentary.** "THIS IS SERIOUS," "catastrophic,"
  "life-threatening" all banned.

## Common commands

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate

# Full test suite
python -m pytest

# Inspect live state
curl -s https://api.github.com/gists/06c02c97ffc0d11458687f1ed998d9e5 \
  | python3 -c "import json,sys;s=json.loads(json.load(sys.stdin)['files']['state.json']['content']);print(len(s.get('drafts',[])),'drafts total,',sum(1 for d in s.get('drafts',[]) if d.get('status')=='pending'),'pending')"

# Recent GitHub Actions runs
gh run list --limit 5 --workflow=bot.yml

# Tail a specific run's log for a source
gh run view <ID> --log | grep -iE '\[draft\]|\[alerts\]|superseded|cooldown'
```
