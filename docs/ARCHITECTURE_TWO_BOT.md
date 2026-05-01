# Two-Bot Architecture — Intern + Editor

**Status:** Spec / pre-implementation. Drafted 2026-04-30. Replaces the
current one-bot Gemini-writes-then-Sonnet-rewrites pipeline.

---

## The reframe

Today both jobs — *what should we say?* and *how should we say it?* —
live inside one Gemini Flash prompt. Sonnet only enters when Gemini's
draft fails the evaluator. That's why we ship phrases like "a large
nuclear reactor generates around 1,000 MW": Gemini is being asked to
do editorial judgment it can't do, and Sonnet only sees the result
after the bad framing is locked in.

Split the jobs by model:

- **Gemini Flash = the intern.** Ingests climate signals, proposes
  many candidate angles per event. High volume, low judgment, cheap.
- **Sonnet 4.6 = the senior editor + writer.** Receives the intern's
  proposals, picks the strongest angle, kills the rest, and writes the
  final tweet in voice. Or returns null if nothing earns "extraordinary."

Sonnet becomes the writer, not the rewriter. Gemini becomes the
explorer, not the writer.

## The editorial filter (north star)

**Every tweet must answer: "why is this extraordinary?"** If it can't,
the draft is killed.

There is **no required formula.** The way a signal earns "extraordinary"
is open-ended:

- A record explanation ("first time since 1929"; "10 weeks past Mali's
  fire-season peak").
- An era anchor ("the last time it was this hot, Steve Jobs was
  introducing the iPod"). Used selectively, not by default.
- A peer-class scale comparison (named, sized, real — "1.4× the output
  of an average gas-fired power plant," not "a large nuclear reactor").
- A geographic or seasonal irony.
- The number alone, plainly delivered, when the number is staggering.

The editor (Sonnet) picks the angle that fits the signal. The intern
(Gemini) proposes options.

## Contract: the story bundle

Gemini's output is no longer a tweet. It's a **story bundle** — a
structured object Sonnet uses as raw material.

```json
{
  "signal": {
    "kind": "fire | heat_record | cold_record | co2 | flood | …",
    "where": "Mali",
    "when": "2026-04-30",
    "headline_metric": {"label": "FRP", "value": 361, "unit": "MW"},
    "raw_facts": [
      {"label": "satellite confidence", "value": 95, "unit": "%"},
      {"label": "mali fire season peak", "value": "February"},
      {"label": "weeks past peak", "value": 10}
    ]
  },
  "candidate_angles": [
    {
      "frame": "off_season",
      "claim": "Mali's fire season peaks in February. This fire is
        burning 10 weeks past that peak.",
      "supporting_facts": ["mali fire season peak", "weeks past peak"]
    },
    {
      "frame": "peer_scale",
      "claim": "361 MW radiative output is roughly 1.4× the output of
        an average ~250 MW gas-fired power plant.",
      "supporting_facts": ["headline_metric"],
      "comparison_class": "gas_plant_avg",
      "comparison_value_mw": 250
    },
    {
      "frame": "rarity",
      "claim": "Largest single-fire FRP recorded in Mali for April since
        VIIRS records began in 2012.",
      "supporting_facts": ["headline_metric"],
      "rarity_window_years": 14
    }
  ],
  "intern_recommendation": "off_season",
  "intern_notes": "Off-season is the strongest hook because the data
    is unusual *for the place at this date*, not just large in absolute
    terms."
}
```

The intern proposes **3-5 angles**, each with the facts that back it.
The intern flags a recommended one but does not decide.

## Editor (Sonnet) responsibilities

Sonnet receives the bundle and:

1. **Verifies the facts.** The intern can hallucinate. Sonnet checks
   each `supporting_facts` reference resolves to real data in the
   bundle. Unsupported facts → angle disqualified.
2. **Picks one angle** (or rejects all and returns null).
3. **Writes the tweet** in voice. No formulas, no banned phrases. The
   existing voice guidance (Wodehouse rule, no stock formulas, no
   restate-padding) applies fully to Sonnet's output.
4. **Stores the choice.** Output includes which angle was picked and
   why, persisted as draft metadata for grading.

Sonnet's writing pass is the *only* writing pass. There is no
Gemini-writes / Sonnet-rewrites loop. That collapses.

## What this kills

- `evaluate_and_polish` rewrite loop → gone. Sonnet writes once.
- `_detect_stock_formula` and friends → still useful, but applied to
  Sonnet's output, not as a filter between two stages.
- Per-category Gemini SYSTEM_PROMPT writing guidance → moved to
  Sonnet's writer prompt. Gemini's prompt becomes "propose angles."
- The era-anchor 1-in-10 deterministic gate → gone. Sonnet just
  doesn't reach for era anchors as a default. Selection is editorial,
  not gated.

## What this preserves

- Gemini Flash as the high-volume reader of raw climate data
  (free-tier `gemini-2.5-flash` if pinned).
- Sonnet 4.6 as the quality bar.
- All existing data sources (FIRMS, NWS, NIFC, Open-Meteo, GRACE-FO,
  ocean SST, river gauges, etc.).
- Set-and-forget. No human in the loop.
- The corpus + grading + daily plan-refinement loop.

## Migration path (sketch — for a separate execution plan)

1. Define `StoryBundle` dataclass and JSON schema.
2. Build new Gemini "intern" prompt: input is structured signal,
   output is `StoryBundle` JSON. No prose, no tweet.
3. Build new Sonnet "editor + writer" prompt: input is `StoryBundle`,
   output is final tweet or null. Inherits all current voice rules.
4. Wire one signal type end-to-end (suggest: fire, since that's where
   the stock-formula bypass bites today). Run in shadow mode beside
   the existing pipeline. Compare outputs in `DRAFT_CORPUS.md`.
5. Promote category-by-category once shadow output beats current.
6. Retire the rewrite path and per-category Gemini writing prompts.

## Open questions

- **Bundle size budget.** 3-5 angles is a guess. Worth A/B'ing 3 vs 5
  vs 7. More angles = more for editor to consider; fewer = lower cost.
- **Comparison library.** "Peer-class" needs a small curated library
  of named, sized benchmarks (gas plant ≈ 250 MW, average US coal
  plant ≈ 547 MW, Hoover Dam ≈ 2,080 MW, etc.) or peer-class is just
  another hallucination axis.
- **Cost.** Sonnet writes every draft instead of only failing rewrites.
  Volume is low (a handful of drafts per cycle, posting paused), so
  this is probably ~$1-3/mo, but worth measuring before promoting.
- **Grading.** Today the corpus grades Gemini's draft + the rewrite as
  separate artifacts. Under two-bot, only one artifact ships. Grading
  should also capture *which angle Sonnet picked* and *which the
  intern recommended* — for a tight feedback loop on Gemini's
  proposal quality.

---

This is the design. Implementation lives in a future session — likely
a separate `docs/TWO_BOT_IMPLEMENTATION_PLAN.md` once the design is
approved.
