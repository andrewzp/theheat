# Manual event portfolio planning

`plan_episode_portfolio` connects current retained NHC episodes to a read-only
editorial plan before any paid writer call. It uses the existing episode resolver,
StoryBundle audit, evidence capture, memory and request preparation. It neither
changes automatic triage nor enrolls work in a queue. Gist remains production.

The current adapter supports source-scoped NHC episodes only. Other hazards,
independent human calibration, the web desk and production dispatch remain open.
This is not evidence of improved global coverage, better copy or measured savings.

## Inputs and evidence binding

Call `src.orchestrator.cyclone_episodes.plan_episode_portfolio` with an existing
local/preview `PhysicalEpisodeSession`, at most 16 exact episode/head targets, an
operator-owned state snapshot, assessments, an explicit as-of instant and a
writing-attempt budget from 0 to 64. It makes no source requests or provider calls.
The repository's normal local/preview environment and source-currentness gates
remain required. A JSON packet cannot replace a repository session.

Start with `assessments=[]`. Every candidate appears with unknown dimensions and
is held. This discovery pass is a template for review, never an invented rating.
For each assessment, copy its exact `binding` from the discovery result:

```python
assessment = {
    "binding": candidate["binding"],
    "dimensions": {
        "impact": None,
        "rarity": None,
        "spatial_scale": None,
        "persistence": None,
        "novelty": None,
        "urgency": None,
        "evidence_quality": None,
        "clear_angle": None,
    },
    "exceptional_reason": None,
}
```

An operator replaces a known dimension with `{"score": 0, "reason": "..."}`
through `{"score": 4, "reason": "..."}` after reading the evidence. Scores are
ordinal editorial judgments: 0 means no additional priority on that dimension;
1–4 indicate increasing priority. Unknown stays `None`, including when evidence
does not support an impact or rarity judgment. Zero never means zero victims or
zero physical hazard. A score does not establish scientific truth, an official
record, observed landfall or a qualified benchmark event.

The exact binding includes the event group, current revision, opportunity, bundle
hash and editorial-policy hash. Changed or foreign bindings refuse the whole
preparation; scores cannot be transplanted onto a newer source. Duplicate
assessments, conflicting heads, malformed factors and unsupported fields refuse.
All eight dimensions need a score and reason before that candidate can rank.
These supplied judgments are not independently verified human benchmark ballots.
Planning eligibility covers source currentness, story audit and these judgments;
it is not an all-route newsworthiness, duplicate, paid-dispatch or posting verdict.

## Selection and retained explanations

The uncalibrated default policy gives each dimension weight 1. The base score is
the sum of the eight weighted components, which remain visible. No raw wind,
rainfall, temperature or fire magnitude is compared across different units.
The planning minimum is 1; it is an explicit editorial setting, not a scientific
threshold or a change to the bot's existing eligibility thresholds.

After eligibility, alternatives from one confirmed episode form one portfolio
item. The highest base-scoring alternative represents it; stable identity breaks
ties. Every alternative and its binding stays in the report and retained source
records remain unchanged.

Selection then subtracts 8 points per already-selected item of the same hazard
and 8 per maximum overlapping geographic-scope count. A multi-country footprint
does not multiply that geographic penalty. Unknown geography has no guessed
country penalty. For NHC, a supplied country uses the existing canonical country
registry; otherwise the known source basin is the editorial scope. Forecast
country membership remains a threat, not observed impact.

An explicit `exceptional_reason` removes these soft diversity penalties for that
candidate, allowing a major regional emergency to dominate. It changes neither
base score nor scientific/source gates and cannot bypass missing assessments,
the planning minimum, event clustering or the writing-attempt budget.

The report retains weighted components, original reasons, repeat counts, applied
penalty, the number of prior selections at that comparison, selection rank and
each unselected disposition. A deterministic plan hash binds the complete report.
Budget 0 keeps the inventory visible and selects nothing. Acquisition coverage
and retained evidence are never reduced to meet this writing-attempt budget.

## Currentness and limits

All requested heads, including unselected and empty ones, are resolved again
before return; editorial policy must still match. The result is explicitly
`checked_at_preparation_only`. Separate reads are not one database snapshot
transaction and the returned object is not a lease or later dispatch grant.
Actual generation still needs fresh authority, budget reservation and all its
required factual/safety checks. Publication and callback authority remain false.

Selected requests contain retained evidence and memory. Keep results private;
do not paste them into public logs. The planner writes no source, state, review,
approval or delivery record. It creates no paid call, measures no actual cost and
enforces no currency or provider-invoice cap. Its attempt count cannot stand in
for the application's spending controls. Complete product acceptance still needs
qualified global events, independent human-ranked comparison and integration
with the authorized production selection and spending paths.
