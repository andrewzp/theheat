# Voice Improvement Plan

Living plan for closing the gap between the bot's current voice quality and the **resumption bar** (majority A-grade rate per cycle). Refined daily by the autonomous grading agent (cron `0 15 * * *`), reviewed and implemented by the human operator.

> **Jul 19: 4 fresh drafts, 25% A-rate (n=4) — same rate as Jul 18, execution- and signal-mix
> driven.** 9 pending (5 Jul 17–18 carry-overs unchanged: Deaver A-, Delhi B+, Anchorage B, Astana
> B+, Wausaukee A-; 4 fresh, 3 of them `absolute_extreme`). 1 A-: Ahvaz, Iran `absolute_extreme`
> (score 84; fresh idiom-flip close, "shade is infrastructure, not comfort" — declarative,
> unstranded, breaks cleanly from A8's reused-clause axis). 2 B+: W Allis, Wisconsin
> `all_time_high` (P_compound overcome by "overwhelms that buffer" — same Great-Lakes
> buffer-failure mechanism as Jul 18's Wausaukee, one day apart in record date, weaker verb); Al
> Basrah, Iraq `absolute_extreme` (**repeats Jul 17 Basrah's exact stranded-mechanic failure** — a
> genuinely declarative buffer-failure line buried as a sentence-1 qualifier while the actual
> closer is a bare peer-comparison fact, "Nearby Basrah is forecast to hit 50.6°C the same day").
> 1 B: Ahvaz/Bandar-E Mahshahr, Iran `absolute_extreme` (mechanism-only close, no threshold
> framing at all — breaks from A8's opener-skeleton shape). **Headline: A8 clears its promotion
> bar on both remaining axes.** The stranded-mechanic shape recurs a 2nd time (Jul 17 Basrah, Jul
> 19 Al Basrah) and the reused survivability-threshold clause a 3rd (Jul 10 Ahvaz "shade and rest
> alone stop being enough" → Jul 17 Basrah "shade and stillness stop being enough" → Jul 19 Al
> Basrah "shade, hydration, and rest stop being adequate buffers") — both now promoted to active
> below. P_close 26th cycle (1 positive, 2 failing). P_compound 14th cycle (W Allis, overcome).
> A4/A5/A6/A7 not tested (no target-type draft this cycle). Zero Wodehouse violations, 4th
> consecutive cycle. P_tier/P_dust/P9 remain CONFIRMED, tracking closed — all 3 fresh
> `absolute_extreme` drafts stayed clean of the banned tier-jargon form. **Operational notes:** 2
> Jul-17 `absolute_extreme` carry-overs (Basrah B+, Al Basrah A-) dropped from the queue, cause
> unconfirmed — same recurring contraction pattern. 0 strict staleness candidates; 1 watch item
> (Ahvaz, forecast-date-elapsed under 48h — same open PR #385 auto-reject question as Jul 11/18).
> `gh` CLI absent, 51st consecutive skip. **Process correction, logged for the operator:** this
> session's Step 0 initially synced only to `main`, which was many cycles behind the rolling
> `daily-plan-current` branch (unmerged since 2026-06-08) and led to briefly re-grading
> already-graded carry-overs before the mistake was caught — corrected by checking out
> `daily-plan-current` directly (confirmed running with no gap since Jul 7). Recommend merging
> `main` soon, or clarifying Step 0 to check the rolling branch first when one exists.
>
> **Jul 18: 4 fresh drafts, 25% A-rate (n=4) — comedown from Jul 17's 80%, signal-mix driven
> (zero fresh `absolute_extreme` this cycle, the type that carried 3 of Jul 17's 4 A-grades).** 7
> pending (3 Jul 17 carry-overs unchanged: Basrah B+, Deaver WY A-, Al Basrah A-; 4 fresh, drawn
> from `precipitation_extreme` ×2 and `air_quality_hazard` ×1 instead). 1 A-: Wausaukee, Wisconsin
> `all_time_high` (P_compound double-qualifier overcome by "without the lake bleeding it off
> first," a named-absence declarative). 2 B+: Delhi, India `air_quality_hazard` (WHO 10.8× stated;
> the strongest device this signal type has produced — a monsoon expectation-reversal, "rains are
> supposed to wash the air... the seasonal scour isn't keeping up" — graded conservatively as
> P_close FAILING per the established `air_quality_hazard` precedent, though flagged explicitly as
> a genuine judgment call that a future grader might read as this type's first P_close-POSITIVE
> instance); Astana, Kazakhstan `precipitation_extreme` (lands the exact baseline-comparison move
> P9 prescribed before its own tracking closed — companion-city triple + annual-average contrast,
> "three cities delivered a sixth of that at once" — but the arithmetic is genuinely ambiguous
> per-city vs. combined, a new clarity/accuracy risk distinct from the four already-catalogued
> Wodehouse violations, capping it below A-). 1 B: Anchorage, Alaska `precipitation_extreme`
> (mechanism-only close, 51× ratio unstated, P_close FAILING). **Headline: A7 promoted from
> awaiting-evidence to an active proposal.** Anchorage's close — "compress moisture into short,
> intense bursts" — is the 3rd instance (Jun 26 → Jul 9 → Jul 18) of the same
> "wring-out/compress-moisture...bursts" phrase family on one station, and the 2nd location (after
> Randolph, Jun 24 → Jul 14) confirming the "writer reuses its own prior closing construction"
> pattern past the 2-location promotion bar A7's Jul 14 filing set. P_close 25th cycle (1
> positive, 1 conservatively-failing, 1 partial/ambiguous, 1 failing). P_compound 13th cycle
> (Wausaukee, overcome). A4/A5/A6/A8 not tested (no signal-kind-self-naming/cyclone/fire/fresh-
> `absolute_extreme` draft this cycle). Zero Wodehouse violations, 3rd consecutive cycle.
> P_tier/P_dust/P9 remain CONFIRMED, tracking closed — untested this cycle (no fresh
> `absolute_extreme`) but not reopened. **Operational notes (not voice proposals):** 4 Jul-17
> drafts dropped from the queue, cause unconfirmed — Bandar-E Mahshahr A-, Tunis A-, interior
> Alaska fire B+, and notably the **western Siberia fire cluster**, the corpus's longest-standing
> staleness candidate (5 consecutive unactioned cycles), plausibly the operator finally acting on
> the repeated reject recommendation, though cause isn't confirmable from the gist alone. 0 strict
> staleness candidates this cycle; **2 watch items** (Basrah ~37.0h, Al Basrah ~29.1h, both
> forecast-date-elapsed-but-under-48h) — reopens the still-unresolved Jul 11 question of whether
> PR #385's forecast-elapsed auto-reject is age-gated by design or has a coverage gap, since
> neither draft was removed ~12–15h past its stated forecast date. `gh` CLI absent, 50th
> consecutive skip (May 13 → Jul 18).
>
> **Jul 17: 5 fresh drafts, 80% A-rate (n=5) — first n≥5 bar-clearing cycle since Jun 29's
> 80%/n=5, and a materially stronger read than Jul 16's small-n 100%.** 7 pending (2 Jul 11 fire
> carry-overs unchanged: interior Alaska B+, western Siberia cluster B+; 5 fresh). 4 A-:
> Bandar-E Mahshahr, Iran `absolute_extreme` ("the air has nowhere to cool" — named-absence
> declarative, clean P_tier form); Deaver, Wyoming `all_time_high` (score 91, batch high; 111yr
> archive — longest in corpus — P_compound double-qualifier overcome by "the terrain that blocks
> moisture also traps heat"); Al Basrah, Iraq `absolute_extreme` ("one of the few places on earth
> where outdoor survival becomes genuinely contested" — batch's strongest declarative, no
> hedging); Tunis `hot10` (leaderboard-aggregate reframe — "heat this far from seasonal average
> has stopped arriving one city at a time," a genuinely new close-shape, 1st cross-cohort framing
> in the corpus). 1 B+: Basrah, Iraq `absolute_extreme` — **stranded mechanic**: its one real
> declarative move ("shade and stillness stop being enough") is buried mid-sentence-1 as a
> qualifier instead of landing in the closer; the actual close is hedged ("rarely what the dry
> number suggests"), P_close FAILING despite a real declarative existing elsewhere in the draft.
> Also a near-verbatim reuse of Jul 10 Ahvaz's "shade and rest alone stop being enough" — **new
> awaiting-evidence item A8 filed**, covering both this reused clause (2 instances now) and a
> same-cycle 3-of-3 `absolute_extreme` opener-skeleton convergence ("[City] is forecast to hit
> XX°C — [above/just inside] the 47°C threshold where..."). P_close 24th cycle (4 positive, 1
> failing — best single-cycle ratio yet). P_compound 12th cycle (Deaver WY, overcome, same
> soften-not-cap pattern). P5: `all_time_high`/`absolute_extreme` self-select again; `hot10`
> confirms a 2nd self-selecting instance (Tunis, after Oslo). A4/A5/A6/A7 not tested (no
> target-type draft). **Zero Wodehouse violations, 2nd consecutive cycle.** P_tier/P_dust/P9
> remain CONFIRMED — all 3 `absolute_extreme` drafts today stayed clean of the banned tier-jargon
> form, further supporting the fix. **Operational notes (not voice proposals):** likely
> duplicate-signal generation (Basrah/Al Basrah, same metro area, 47.9°C vs 48°C, 8h apart —
> graded independently per the Jul 3 precedent, and correctly: their quality diverges sharply);
> signal-mix monoculture (3 of 5 fresh drafts `absolute_extreme`, all Persian Gulf/lower-
> Mesopotamian — the 80% A-rate leans on that type's current strength more than a fully diverse
> batch would). **Western Siberia fire cluster now unactioned for a 5th consecutive cycle
> (~152.8h), the corpus's longest-standing staleness candidate to date.** Write skipped — `gh`
> CLI absent, no gist-write tool available via the GitHub MCP server this session (49th
> consecutive skip, May 13 → Jul 17).
>
> **Jul 16: 2 fresh drafts, 100% A-rate (n=2) — first 100%-of-cycle reading since Jun 22's
> retroactive n=1.** Queue contracted sharply: 4 of Jul 15's 6 pending drop (Stevensville A-,
> Riyadh dust_event B+, Tepee Creek B+, Basrah A-), leaving only the 2 Jul 11 fire carry-overs
> (interior Alaska B+, western Siberia cluster B+, both unchanged) plus 2 fresh. **Operational
> finding:** `main`'s `bot.yml` posting/drafting/leaderboard schedules were stopped 2026-07-14
> 12:49 ET (`#441`) and restored 2026-07-15 22:46 ET (`#449`) — this timeline lines up exactly
> with Jul 15's zero-fresh-draft cycle and today being the first fresh drafts since the restore
> (Powderville 10:05 UTC, Oslo 14:09 UTC), and is the likely (if unconfirmed) explanation for
> today's contraction too. 2 A-: Powderville, Montana `all_time_high` (63yr archive, 4°F margin —
> P_compound double-qualifier present, 11th cycle, overcome by a declarative named-absence close,
> "no marine layer... no terrain to interrupt heat building," same family as Basrah's "no
> evaporative relief"); Oslo `hot10` (+10.4°C July anomaly — peer/climate-analogy comparison +
> declarative accelerating-warming reframe, "is what a warmer baseline looks like at high
> latitudes," same interpretive-reframe shape as Jun 29's marine_heatwave A-; first `hot10` draft
> graded under this framework, n=1). P_close 23rd cycle (2 positive, 0 failing) — with P_tier,
> P_dust, and P9 all shipped and confirmed (Jul 14), **P_close and P_compound are now the only
> two structural levers left** between the pipeline and a sustained majority-A cycle, and today's
> cycle is a clean small-n demonstration of both landing correctly in the same draft. P_compound
> 11th cycle (Powderville, overcome). P5: `all_time_high` self-selects again (extreme-heat/record
> family streak extends); `hot10` self-selects a real mechanic on its corpus debut. A4/A5/A6/A7
> not tested (no target-type draft). **1 strict staleness bulk-reject candidate, 4th consecutive
> unactioned cycle and the corpus's oldest to date:** western Siberia fire cluster (~128.7h,
> present-tense "today" still in the text). Write skipped — `gh` CLI absent, no gist-write tool
> available via the GitHub MCP server this session (48th consecutive skip, May 13 → Jul 16).
>
> **Jul 15: 0 fresh drafts; queue contracted from 8 to 6 (Randolph, Utah `all_time_high` B+
> and Ontario, Canada `fire` C+ both drop, cause unconfirmed).** Remaining 6 pending are an
> exact match to prior grading — Stevensville, Maryland `all_time_high` (A-, Jul 9), Riyadh,
> Saudi Arabia `dust_event` (B+, Jul 10), Tepee Creek, Montana `all_time_high` (B+, Jul 10),
> interior Alaska `fire` (B+, Jul 11), western Siberia 3-signal `fire` cluster (B+, Jul 11),
> Basrah, Iraq `absolute_extreme` (A-, Jul 14); no re-grading performed, all grades stand.
> Randolph and Ontario's disappearance is another instance of this plan's recurring
> unexplained queue-contraction pattern (after Anchorage Jul 10→11, Ahvaz Jul 11→12) — losing
> Ontario in particular removes the corpus's cleanest live P5 counter-instance test case from
> the pending queue, though the Jul 14 grading record and its evidence stand regardless of
> queue presence. No active-proposal evidence updates this cycle (no fresh drafts): **P_close**
> (22 cycles), **P_compound** (10 cycles), **P5**, **A4/A5/A6/A7** all retain their Jul 14
> counts and "Last seen" dates. P_tier/P_dust/P9 remain CONFIRMED, tracking closed. **Western
> Siberia fire cluster crosses into a 3rd consecutive unactioned staleness cycle** (~104.7h old
> at grading, present-tense "today" still in the text; flagged Jul 13 at ~56.6h, Jul 14 at
> ~80.6h). Write attempted and skipped — `gh` CLI absent, no gist-write tool available via the
> GitHub MCP server this session (**47th consecutive skip**, May 13 → Jul 15). Operator should
> reject the western Siberia draft via dashboard, independent of any A-rate/posting decision.
>
> **Jul 14: 3 fresh drafts, 5 carry-overs, 33% A-rate. Headline: P_tier's tracking closes —
> all three of this plan's shipped code fixes (P_tier, P_dust, P9) are now CONFIRMED.** Basrah,
> Iraq `absolute_extreme` ([7], A-) is the 2nd independent post-fix confirmation on a named
> target type (after Jul 10's Ahvaz): "3°C above the 47°C threshold where the body's cooling
> mechanisms begin to fail faster than they can recover" — no band-label/tier-jargon citation,
> the same clean form PR #386 prescribed, plus a declarative P_close ("removes the ceiling").
> 1 B+: Randolph, Utah `all_time_high` ([6], 134yr archive, standard P_compound double-
> qualifier — 10th cycle; P_close implied/failing — "normally bleeds off the heat that pools
> across the Great Basin floor" is a near-verbatim echo of this same city's own Jun 24 corpus
> draft's "normally blunts the heat," 20 days apart, a different record type — **new
> awaiting-evidence item A7 filed**). 1 C+: Ontario, Canada `fire` cluster ([8], 2,374.8/883.7/
> 817.1 MW — **P5 counter-instance, breaks fire's 6-cycle self-selection streak**: a bare
> 3-signal-count restatement with zero ecosystem-specific mechanic, notable because this same
> cycle's western Siberia carry-over proves the multi-fire-cluster framing and a real mechanic
> are compatible when the writer reaches for one). P_close 22nd cycle (1 positive: Basrah; 1
> failing: Randolph). P_compound 10th cycle. A4/A5/A6 not tested (no target-type draft). **1
> strict staleness bulk-reject candidate, 2nd consecutive cycle unactioned:** western Siberia
> fire cluster (~80.6h old, present-tense "today" still in the text). Write skipped — `gh` CLI
> absent, no gist-write tool available via the GitHub MCP server this session (46th consecutive
> skip). Bot commit note: `main`'s `VERSION` now reads `0.9.100.0` (was `0.9.97.0` per the Jul 8
> BRIEFING.md snapshot this plan has been citing); intervening `main` commits are a new
> `heat_records_cluster` signal type (#414, default-OFF, manual-approval-only, no instance in
> today's queue) plus unrelated docs/economics work — not expected to affect grading.
>
> **Jul 13: 0 fresh drafts.** Queue is an exact match to Jul 12's 5 graded drafts (Stevensville
> MD A-, Riyadh dust_event B+, Tepee Creek MT B+, interior Alaska fire B+, western Siberia fire
> cluster B+); no re-grading performed, all grades stand. No active-proposal evidence updates
> this cycle — P_close, P_compound, P5, P_tier, P_dust, P9, A4, A5, and A6 all retain their Jul
> 12 counts and "Last seen" dates. **1 new strict staleness bulk-reject candidate:** western
> Siberia fire cluster crosses 48h (~56.6h) with present-tense "today" still in the text — the
> exact crossing flagged proactively in the Jul 11 and Jul 12 entries. Write skipped (`gh` CLI
> absent, no gist-write tool available via the GitHub MCP server this session — 45th consecutive
> skip). **Docs-freshness note:** `main`'s copies of these three docs were still frozen at their
> Jul 6 state at this session's start — the Jul 7 `#384` merge was a one-time snapshot, not a
> standing sync, and nothing had refreshed `main` in the 6 days since. The rolling
> `daily-plan-current` branch itself had NOT gone stale: it carries an unbroken daily run
> Jul 7–12 (`main`'s corpus merge, the P_tier/P_dust code fixes, and every cycle's grading are
> all already reflected there). This session rebased cleanly onto fresh `main` (docs-only,
> zero conflicts) before appending here — recommend the operator periodically fast-forward
> `main`'s copies of these three docs even outside program-adoption milestones, so a future
> session's Step-0 sync doesn't mistake the rolling branch's genuine currency for staleness.
> **P_tier still needs a 2nd post-fix confirmation** on a fresh `absolute_extreme`/
> `fire_footprint`/cyclone/`regional_sst_anomaly` draft — none of today's 5 carry-overs qualify.
>
> **Jul 12: 0 fresh drafts.** 5 pending — exact match to 5 of Jul 11's 6 graded drafts
> (Stevensville MD A-, Riyadh dust_event B+, Tepee Creek MT B+, interior Alaska fire B+,
> western Siberia fire cluster B+); no re-grading performed, all grades stand. **Ahvaz, Iran
> `absolute_extreme` (A-) drops from the queue** — cause unconfirmed, 2nd consecutive cycle of
> unexplained single-draft contraction (Anchorage dropped Jul 10→11; now Ahvaz Jul 11→12).
> Losing Ahvaz costs the corpus its best open P_tier test case — it was 1 of the 2
> confirmations this proposal's tracking needs to close; the Jul 10 grade record stands, but
> closing P_tier now needs a fresh `absolute_extreme`/`fire_footprint`/cyclone/
> `regional_sst_anomaly` draft. No active-proposal evidence updates this cycle — P_close,
> P_compound, P5, P_tier, P_dust, P9, A4, A5, and A6 all retain their Jul 11 counts and "Last
> seen" dates. 0 staleness candidates (Stevensville/Riyadh/Tepee Creek past-tense carve-out;
> both fires <33h; western Siberia's "today" still under 48h, watch ~2026-07-13T06:25Z). `gh`
> CLI absent, 44th consecutive skip.
>
> **Jul 11: 2 fresh drafts, 4 carry-overs (partial turnover), 0% A-rate.** 4 of Jul 9/10's
> drafts survive unchanged (Stevensville MD A-, Riyadh dust_event B+, Tepee Creek MT B+,
> Ahvaz A-); Anchorage AK precipitation_extreme drops from the queue (cause unconfirmed). 2
> fresh, both `fire`, both graded B+: interior Alaska (926.3 MW, 66°N, "doesn't just consume
> trees — it burns into the organic layer above the frozen ground" — 6th permafrost-carbon-
> mechanic instance) and a western Siberia 3-signal comic-triple cluster (1,387.9/958.0/
> 720.7 MW, "burning across peat that took centuries to accumulate"). Both close in the
> mechanic's established declarative-but-weak P_close form (positive, same tier as Jul 3's
> near-dup). **Headline: new proposal A6 filed** — the permafrost-carbon fire mechanic,
> this plan's most reliable fire-category A-grade path (6 corpus instances, all B+/A-),
> shows its first sign of reusing a prior draft's exact phrasing on a *different* fire
> event: Alaska's close reuses Jul 5 eastern Siberia's "doesn't just X — it Y" contrastive-
> negation construction near-verbatim; Siberia's close reuses Jul 3's near-duplicate
> Canadian Arctic close's exact clause, "...that took centuries to accumulate." This is
> distinct from the already-tracked within-location duplicate-generation anomaly (same
> bundle/event re-issued under a new draft_id) — here the writer is reaching for its own
> prior sentence shape across genuinely different locations/dates/readings. 1 cycle; watch
> for a 3rd instance before promoting to an active proposal, per the A3/A4/A5 precedent.
> P_close 21st cycle (2 positive, both weak-declarative). P5: fire self-selects again (5th/
> 6th consecutive confirming cycle) — same organic-deployment pattern now showing early
> signs of formulaic drift. P_tier/P_dust/P9/P_compound/A4/A5 not tested this cycle (no
> target-type draft among the 2 fresh). 0 staleness candidates (Stevensville/Riyadh
> past-tense carve-out regardless of age; all others <29h); 43rd consecutive `gh` skip.
> **Operator note:** Ahvaz's forecast date (July 10) has elapsed but sits under 48h — worth
> confirming whether PR #385's forecast-elapsed auto-reject is age-gated by design or has a
> gap here.
>
> **Jul 10: 3 fresh drafts, 2 carry-overs (complete-turnover streak breaks), 33% A-rate.**
> First non-full-turnover cycle since Jul 6: Stevensville MD (A-) and Anchorage AK (B) survive
> from Jul 9, ungraded, alongside 3 fresh. **Headline: P_tier's first post-fix confirmation on
> a named target type.** Ahvaz, Iran `absolute_extreme` — the exact signal type this proposal
> targeted — reaches pending 3+ days post-#386 with no band-label/tier-jargon citation ("just
> above the 47°C threshold where heat in this part of the Middle East historically crosses into
> the range where shade and rest alone stop being enough" vs. this same city's Jul 7 pre-fix
> "above the 47°C absolute-extreme threshold for the Northern Subtropics"). Paired with a
> strong declarative P_close, this is the corpus's **first A-grade `absolute_extreme` draft**
> — graded A-. **P_dust closes its tracking**: Riyadh `dust_event` states its WHO multiple for
> a 2nd independent post-fix cycle (24.9×, after Jul 8's 27.9×), same 2-clean-cycles bar P9
> used to close Jul 9. Riyadh graded B+ (close still structural, not declarative — P_close's
> orthogonal gap persists). Tepee Creek, MT `all_time_high` graded B+ (standard P_compound
> double-qualifier + implied P_close, 9th P_compound cycle). **P_close 20th cycle** (1
> positive: Ahvaz; 2 failing/borderline: Riyadh, Tepee Creek). **P_tier: 1 post-fix
> confirmation** — watch for a 2nd on any of the 4 target types before moving to Resolved,
> same position P_dust was in after Jul 8. **P_dust: 2nd post-fix confirmation — tracking
> closes.** A4/A5 not tested (no `air_quality_hazard`/`cyclone_land_threat` draft). 0 stale
> drafts (oldest carry-over ~35.7h); 42nd consecutive `gh` staleness skip.
>
> **Jul 9: 2 fresh drafts, complete queue turnover (4th occurrence), 50% A-rate (n=2, not
> a majority) — 2nd consecutive cycle landing exactly on the half-boundary.** All 8 of
> Jul 8's drafts are gone; 2 fresh, both created 2026-07-09T03:26–03:29Z. 1 A-:
> Stevensville, Maryland `all_time_high` (103°F, "beating a record from 1934, by 2°F, in
> 101 years of data" — **P_compound's worst instance to date**, a triple-stacked
> qualifier one past every prior double-qualifier form; overcome by a clean
> buffer-failure declarative close, "that buffer failed," same shape as Jun 29's Congo
> fire A-). 1 B: Anchorage, Alaska `precipitation_extreme` (61.2mm/day against a 0.9mm
> prior record — exactly 68×, the corpus's most dramatic precip ratio, left unstated;
> P9-clean of restate-math and the legacy template, but P_close FAILING on "wring out
> moisture in concentrated bursts" — one word from Jun 26's own Anchorage draft, "wring
> out moisture in compressed bursts," and notably weaker than this same station's Jul 8
> A- draft two days earlier on a different bundle metric [7-day accumulation vs. daily
> record]). **P9 gets its 2nd independent clean cycle (Jul 8 3/3 + Jul 9 1/1) — closing
> the tracking**, though today's instance also shows the fix's benefit may be
> metric-shaped (proven on accumulation bundles, not yet on daily-record bundles). P_close
> 19th cycle (1 positive, 1 failing). P_compound 8th cycle (new worst instance). P_tier
> still not tested on a named target type (none appeared Jul 7, 8, or 9). P_dust/A4/A5
> not tested (no target-type draft). 41st consecutive `gh` staleness skip (0 candidates —
> both same-day fresh).
>
> **Jul 8: 8 fresh drafts, complete queue turnover (3rd occurrence), 50% A-rate — closest
> approach to the bar since Jun 29's 80% clearance** (50% is exactly half, not a
> majority, so the bar is technically not cleared). All 8 drafts postdate every fix
> shipped since Jul 5 (#386 P_tier/P_dust, #397 precip four-moves/P9, #404 cyclone
> four-moves) — **the first cycle where every fresh draft is safely post-fix for all
> three.** **P_dust and P9 are both empirically confirmed clean for the first time.** 4
> A-: Barrow AK precip ("one storm just delivered two-thirds of a normal year in a day"
> — first fully clean `precipitation_extreme` draft in corpus history); Astana precip
> (same clean ratio-close form); Anchorage precip (ratio-anchor leads sentence 1,
> declarative orographic close — best-constructed of the three); Riyadh
> air_quality_hazard ("basin-scale loading, not a street-corner spike" — new
> scale-honesty-contrast close subtype; A4 does not recur). 3 B+: Snowshoe WV
> all_time_high (P_compound 7th cycle; P_close failing — notably weaker than this same
> station's Jul 7 A- draft one day earlier); Typhoon Bavi `cyclone_landfall` (**new
> signal type**, P_close positive, but a 2nd raw-JTWC-URL bundle-leak bug); Riyadh
> dust_event (**P_dust fix confirmed** — 27.9× WHO PM10 stated, closing the 11-for-11 gap
> tracked since Jun 13; P_close still failing, mechanism-only, untouched by the WHO-anchor
> fix — the two proposals are orthogonal). 1 B: Typhoon Bavi `cyclone_land_threat` (**new
> signal type**, the kind PR #388 added to close the "Bavi gap" — forecast-tense rules
> followed precisely, but P_close fails on a purely expository debut close, same as every
> other type's first appearance). P_close 18th cycle (5 positive, 3 failing; 16th/17th
> confirmed signal types via the two new cyclone kinds). P_compound 7th cycle. P_tier not
> tested on a named target type this cycle (no `absolute_extreme`/`fire_footprint`/
> `cyclone_rapid_intensification`/`regional_sst_anomaly` draft; the 2 new cyclone kinds
> are governed by the same rule and came back clean, which is supporting but not
> definitive evidence). **Operator notes:** possible Bavi landfall/land_threat
> bundle-sequencing inconsistency (verify advisory timestamps before publishing both
> today's Bavi drafts); 2nd occurrence of the raw-URL bundle-leak bug (flag to engineer
> directly). 40th consecutive `gh` staleness skip (0 candidates this cycle).
>
> **Jul 7: 6 fresh drafts, complete queue turnover (2nd occurrence), 33% A-rate — best
> cycle since Jul 3.** **Major overnight pipeline push, most consequential cycle for this
> plan to date:** `main` MERGED (#384, 2026-07-06T23:42Z) — the 29-cycle "unmerged since
> Jun 8" saga is over. **P_tier and P_dust SHIPPED as code** (#386, "detection-plumbing
> ban + dust PM10 WHO anchor," merged 2026-07-07T05:06:48Z) — moved from Active to
> Shipped below, awaiting empirical confirmation. **Basra-class staleness got a
> structural pipeline fix** (#385, forecast-elapsed auto-reject, merged
> 2026-07-07T04:55:15Z) — very likely why the 2 unactionable bulk-reject candidates
> flagged Jul 6 are simply gone from today's queue, along with all 13 other carry-overs.
> 2 A-: Snowshoe, WV all_time_high (P_compound overcome by a declarative
> elevation-inversion close); Soweto air_quality_hazard (**first A- for this type** —
> "nowhere to vent"). 3 B: Ahvaz absolute_extreme (pre-fix P_tier violation, strong
> close); Aibonito, Puerto Rico **`record` — new signal type debut** (day-of-year
> record, P_close mechanism-only on its first instance, same as every type's debut); Riyadh
> air_quality_hazard (post-fix, but "This is a PM2.5 signal, not dust" is a fresh
> self-reference variant — **new proposal A4 filed**). 1 B-: Zaragoza absolute_extreme
> (pre-fix P_tier violation on a new band name, "northern mid-latitudes"). **Fix-timing
> straddle:** the 2 P_tier violations here (Zaragoza, Ahvaz, 03:39/03:40 UTC) predate the
> 05:06 UTC fix by ~1.5h; the 4 post-fix drafts are all non-targeted types — neither
> P_tier nor P_dust is empirically confirmed yet. P_close 17th cycle (3 positive, 3
> failing; 15th signal type via `record`). P_compound 6th cycle (Snowshoe).
> `air_quality_hazard` self-selects for a 4th consecutive cycle. 39th consecutive `gh`
> staleness skip (0 candidates this cycle).
>
> **Jul 6: 0 fresh drafts — queue is an exact match to Jul 5's 15 graded drafts (same
> `draft_id`s, scores, text); no re-grading performed, all grades stand at Jul 5's levels.**
> No active-proposal evidence updates: P_close (16 cycles), P_tier (7 cycles/10 instances),
> P_dust (9 cycles), P9/P_compound (not tested since Jul 4) all unchanged. **2 new strict
> staleness bulk-reject candidates:** Basrah and Al Başrah al Qadīmah `absolute_extreme`
> (both >48h old — 56.2h/52.8h — with a stated forecast date of July 4 now two days elapsed),
> same Basra-area class flagged Jul 1–3; write skipped (`gh` CLI absent, no gist-write tool
> available via the GitHub MCP server this session — 38th consecutive skip). Doha's forecast
> date (July 5) has also elapsed but sits under 48h — watch for it crossing the threshold next
> cycle. **Operator: `main` remains unmerged since 2026-06-08 — now 29 consecutive daily cycles
> (including the Jun 29 bar-clearing 80% cycle) live only on `daily-plan-current`.**
>
> **Jul 5: 15 pending (10 carry-overs from Jul 4 + 5 fresh), 20% A-rate (small-n, consistent
> with Jul 4's 20%/n=10).** 1 A-: **eastern Siberia fire** (556.1 MW, "doesn't just burn the
> surface — it thaws the ground beneath it" — 4th corpus confirmation the permafrost-carbon
> fire mechanic reliably clears P_close, joining Jun 25 Siberia + Jul 3 Canadian Arctic ×2).
> 1 B+: Johannesburg air_quality_hazard (10.9× WHO stated, richer causal chain than Jun 24's
> Al Aḥmadī — named season + source attribution — but P_close failing on an
> accumulation-not-consequence close). 1 B: **Doha, Qatar absolute_extreme — P_tier confirmed
> outside the Basra-area cluster for the first time** (same tier-jargon phrase on a city
> 1,500+ km from Basrah, proving the violation is bundle-field-tied, not location-tied);
> P_close positive with the sharpest close the signal type has produced ("closing off the
> evaporative cooling that makes extreme dry heat survivable"), still capped at B — P_tier's
> hard-ceiling behavior holds regardless of close quality. 1 B-: 3rd Urumqi dust_event draft —
> same station, 3rd distinct reading, near-verbatim repeat of the same resolution-form close
> for a 3rd time (new subtype: frozen mechanism, varying reading, distinct from the
> exact-duplicate-generation pattern). 1 C+: Phalodi, India dust_event (10th dust_event corpus
> draft, no WHO anchor, no named mechanic). **P_close 16th cycle** (2 positive, 3 failing).
> **P_tier 7th cycle / 10 instances / 1st cross-location confirmation** — now the strongest
> evidence yet that this is a structural bundle-field problem. **P_dust 9th cycle** (Phalodi +
> Urumqi; 11 of 11 dust_event instances still without a WHO anchor, while the sibling
> air_quality_hazard type keeps stating it unprompted — the cleanest existence-proof yet that
> the fix is achievable without new architecture). P9 and P_compound not tested this cycle (no
> precipitation_extreme or record-type draft among the 5 fresh). 0 stale drafts; 37th
> consecutive `gh` staleness skip. **Operator: `main` remains unmerged since 2026-06-08 — now
> 28 consecutive daily cycles (including the Jun 29 bar-clearing 80% cycle) live only on
> `daily-plan-current`.**
>
> **Jul 4: complete queue turnover — 10 pending, all fresh, 0 carry-overs, 20% A-rate
> (largest statistically-meaningful sample since Jun 29's bar-clearing n=5).** Every one
> of Jul 3's 20 pending drafts — including the 4 strict bulk-reject candidates and 13
> clean carry-overs — is gone from the queue; cause unconfirmed (bulk-reject, bulk-publish,
> or TTL/other sweep — operator should verify). 2 A-: **Typhoon Bavi**, the 2nd
> `cyclone_rapid_intensification` draft in corpus, avoids the P_tier tier-jargon violation
> that capped Jul 3's 1st instance at C+ and lands the type's first P_close-positive close
> ("storms... can intensify faster than forecasters or ships can react") — first
> counter-instance suggesting the two known traps aren't deterministic-per-bundle-field;
> **Loxahatchee FL** all_time_high ("the column runs free" overcomes a P_compound
> double-qualifier opener, same pattern as Jun 29's Prudhoe Bay). 2 B+: Island Pond VT
> all_time_high (P_compound + P_close failing/hedged) and **Antwerpen precip — a
> value-identical re-issue of the Jun 30 B+ draft under a new draft_id**, a new
> cross-day variant of the duplicate-generation pattern. 6 B: Barrow + Astana
> precipitation_extreme (**P9 reopened** — both repeat the archived opener-template +
> restate-math pattern on the very first reappearance, exactly as predicted when it was
> archived Jul 3; Astana's close is a new P_close low — a bare fact with no mechanism or
> consequence, stranding the batch's best joke: 358mm in a week vs. a ~300mm annual
> average); Basrah + Al Başrah al Qadīmah absolute_extreme (4th/5th Basra-area instances,
> both repeat the P_tier violation, both cap at B regardless of close quality — consistent
> with [11]/[16] precedent); Rocky Mountains CO fire (mid-latitude drought-mechanism-only
> class, same as Jun 30's Colorado B-). **P_close 15th cycle** (3 positive, 6 failing).
> **P_tier 6th cycle / 9 instances / still 4 signal types** (2 new absolute_extreme
> violations, 1 clean cyclone_rapid_intensification counter-instance). **P_compound 5th
> cycle** (2 instances, both all_time_high). **P9 reopened** after exactly 1 archived
> cycle. P_dust continues (Urumqi, 9th-ish dust_event draft, still no WHO anchor). No new
> proposals — duplicate-generation and the queue-turnover are logged as operational
> anomalies, not voice proposals, per the hard constraints. 0 stale drafts this cycle (all
> 10 same-day fresh); 36th consecutive `gh` staleness skip.
>
> **Jul 3: 20 pending, 3 fresh graded, 33% A-rate this cycle (small n; bar cleared Jun 29 still
> stands as the most recent above-bar cycle).** 17 of 20 pending are carry-overs from Jun 28–Jul 2,
> grades unchanged. 3 fresh: Canadian Arctic fire A- (792 MW, "reaches carbon the frozen ground
> has held for millennia" — 3rd P_close-positive carbon-release fire close, strongest execution
> yet); a near-duplicate Canadian Arctic fire B+ (same signal, drafted 68 seconds later, weaker
> "centuries"/"organic soil layers" close); Typhoon Bavi C+ (first `cyclone_rapid_intensification`
> in corpus — "the rapid-intensification threshold is 30 kt in 24 hours" is **P_tier's 4th signal
> type**, capping an otherwise-real ratio-as-punchline close; a raw JTWC source URL is appended to
> the tweet text itself, likely a bundle-leak bug flagged for the engineer, not folded into the
> grade). **P_close 14th cycle** (2 positive). **P_tier 5th cycle / 7th instance / 4 signal types**
> — now demonstrably the most *actively capping* proposal in back-to-back-to-back cycles even
> though P_close has more total cycles. **P9 archived this cycle** (3 consecutive fresh-draft
> cycles — Jul 1/Jul 2/Jul 3 — without a precipitation_extreme draft to test it against; the
> proposal itself remains strongly evidenced from its first 9 cycles and should still ship). No
> dust_event or record-type drafts this cycle — P_dust/P_compound/P5 unchanged. **Duplicate-signal
> generation confirmed a 3rd time across a 3rd signal type** (Ft Green all_time_high, Basrah
> absolute_extreme, now Canadian Arctic fire) — operational, not a voice proposal, flagged for the
> operator again. 2 stale carry-overs now at 4th/3rd consecutive cycles unactioned (Mediterranean
> SST, GMST marine_heatwave), plus [11]/[13] Basra-area `absolute_extreme` newly cross the 48h
> mechanical threshold on top of their already-elapsed forecast dates — 4 strict bulk-reject
> candidates this cycle, most in one cycle since the pattern started. 35th consecutive staleness
> skip. **Operational note, now urgent: `main` has not merged this branch since 2026-06-08 — 25
> consecutive daily cycles are stranded here, including the Jun 29 bar-clearing (80%) cycle a
> `main`-only view would never see. Recommend the operator merge soon.**
>
> **Jul 2: 17 pending, 3 fresh graded, 0% A-rate this cycle (bar cleared Jun 29 still stands as
> the most recent above-bar cycle).** 14 of 17 pending are carry-overs from Jun 28–Jul 1, grades
> unchanged. 3 fresh, all B-range or below, forming two duplicate-location clusters: Ft Green,
> Florida all_time_high B (102°F, June 28, "the lid lifts fast" — P_close borderline positive) and
> a second near-identical Ft Green draft one day later, all_time_high C+ (102°F, June 29, same
> 26yr/1°F margin, weaker "overcome that convective ceiling" close that restates the headline
> number); Basrah, Iraq absolute_extreme B (48°C forecast for July 1 — third Basra-area draft in 3
> days, same P_tier tier-jargon leak as Jul 1's two Basra drafts, strong named-absence close).
> **P_tier 4th cycle / 6th instance** (was promoted from A3 yesterday; today adds a 3rd near-verbatim
> Basra-area repeat of the exact phrase family). **P_compound 4th cycle** (both Ft Green drafts open
> with the archive-depth + margin double-qualifier, same pattern as Beaver Dams/Casper/Prudhoe Bay).
> **P_close 13th cycle** (1 positive: Basrah; 1 failing: 2nd Ft Green; 1 borderline: 1st Ft Green).
> No precipitation_extreme or dust_event drafts this cycle — P9/P_dust/P5 unchanged;
> **P_precip_floor archived** (3 consecutive fresh-draft cycles without a qualifying wet-climate
> thin-margin observation). 2 carry-overs still stale and unactioned for a 2nd–3rd consecutive cycle: Mediterranean
> SST and GMST marine_heatwave. **New operational observation:** all 3 `absolute_extreme` corpus
> drafts now cite forecast dates that have elapsed by grading time (none crosses the mechanical 48h
> threshold, but all 3 would misstate the date if posted) — recommend the operator pick at most one
> Basra-area draft to post and reject the other two. 34th consecutive staleness skip.
>
> **Jul 1: 14 pending, 4 fresh graded, 0% A-rate this cycle (bar cleared Jun 29 still stands as
> the most recent above-bar cycle).** 10 of 14 pending are carry-overs from Jun 28–30, grades
> unchanged. 4 fresh, all B-range or below: Basrah, Iraq absolute_extreme B (score 83, "offers
> no evaporative relief" P_close positive); Morrill Fire, Nebraska fire_footprint B (first of
> type; "the underlying sand can begin to shift" — best closer in the batch); Al Baṣrah al
> Qadīmah, Iraq absolute_extreme B- (same Basra metro area as the Jun-30 Basrah draft, 3 days
> later, softer close); Wadi Halfa, Sudan dust_event C+ (8th consecutive dust_event draft, no
> WHO anchor, best two-step mechanism yet). **New: P_tier promoted from A3 (awaiting-evidence,
> filed Jun 23) to active proposal** — 4 of today's 14 pending drafts across 3 signal types
> (`regional_sst_anomaly`, `absolute_extreme` ×2, `fire_footprint`) state an internal scoring-tier
> name verbatim ("the 47°C absolute-extreme threshold for the Northern Subtropical band," "the
> 250,000-hectare tier that marks a continent-scale footprint") instead of describing the world —
> a Wodehouse violation (citing methodology) distinct from the previously-named forms. P_close
> 12th cycle (2 positive: Basrah, Morrill Fire; 2 failing: Al Baṣrah, Wadi Halfa). P_dust 7th
> cycle (Wadi Halfa, 8th corpus draft, template convergence total). 2 carry-overs newly/still
> stale: Mediterranean SST (~83h, unactioned since Jun 30's flag) and GMST marine_heatwave
> (~70h, newly crossed 48h). **Operational note: `main` is stale since Jun 8 — this and the prior
> ~23 daily cycles (Jun 9–Jun 30) live only on the unmerged `daily-plan-current` branch.**
> Operator should merge soon. 33rd consecutive staleness skip.
>
> **Jun 30: 10 pending, 9 graded, 22% A-rate (bar cleared Jun 29 still stands).** 1 stale excl.: Mediterranean regional_sst_anomaly (~59h, "today" baked). 2 A-: GMST marine_heatwave A- (floor/ceiling inversion "already the floor of a new streak"); Prudhoe Bay all_time_high A- (score 92, 101°F at 70°N, latitude peer-comparison). 5 B: France reganom B+, Astana B+, Antwerpen B+, Amsterdam B, Colorado B-. 2 C+: Phalodi + Taiz dust_event (P_dust 5th+6th cycle, zero named mechanics, no WHO anchor). P9 9th cycle: 3/3 fresh precip drafts (Astana/Antwerpen/Colorado) show opener template + restate-math. P5: dust_event continues to deploy zero named mechanics (2nd cycle confirming gap category). regional_anomaly corpus debut: France reganom B+ (score 88, 6-city +8.4°C avg, 2.8σ — first reganom in corpus post-#349). P_compound: Prudhoe Bay shows archive+margin double-qualifier (3rd cycle). 22% A-rate reflects different signal mix vs. Jun 29 — fewer A-grade-prone signal types in queue. GMST marine_heatwave approaching 48h staleness (~45.7h at grading) — publish promptly. 32nd consecutive staleness skip.
>
> **Jun 29: 5 fresh drafts (80% A-rate — BAR CLEARED).** 1 Jun-28 carry-over (Mediterranean B+, grade stands). [2] marine_heatwave A- (floor/ceiling inversion; "already the floor of a new streak"; P_close positive). [3] France reganom B+ (pre-#349; "Across 6 sampled cities" buries lede; "hour by hour" Wodehouse mild; P_close failing). [4] Congo fire A- (first A-grade fire in two-bot corpus; ecosystem incongruity "something has broken the convective lid"; P_close positive). [5] Prudhoe Bay all_time_high A- (latitude peer-comparison 91°F at 70°N vs. northern Siberia rarely 80°F; P_compound 2nd cycle — archive+margin double-qualifier). [6] Amsterdam precipitation_extreme A- (declarative close "there is nowhere for the water to go"; P_close positive; P9 8th cycle; P_precip_floor 2nd cycle — 4.7% margin wet-climate). P_close 11th cycle: 3 positives, 1 failing, 1 n/a. New signal type in corpus: marine_heatwave. No Wodehouse violations (8th consecutive clean). `gh` CLI absent (31st consecutive skip).
>
> **Jun 28: 5 fresh drafts (0% A-rate).** 2 Jun-27 carry-overs not re-graded ([1] fire B+, [2] Amsterdam C+). [3] Taiz dust_event C+ (P_dust 4th cycle, no WHO anchor; P_close mechanism-only fail). [4] Mediterranean SST B+ (P_close borderline positive "nowhere fast to go"). [5] Astana precip B+ (51.1/3.9 mm implicit 13×, steppe closer; P9 7th cycle). [6] Beaver Dams all_time_high B+ (P_compound new — archive+margin double-qualifier; P_close implied fail). [7] Casper monthly_low B (P_compound 2nd obs; P_close implied fail). P_close 10th cycle; 3 failing, 1 borderline positive, 1 n/a. New proposal P_compound. `gh` CLI absent (30th consecutive skip).
>
> **Jun 26: 3 fresh drafts (0% A-rate).** All precipitation_extreme. Anchorage B (183.8 mm/3d,
> 22.5% margin, orographic stall mechanism, P_close mechanism-only failing). Amsterdam C+ (157.1
> mm, 4.73% margin, canal-capacity incongruity, P_close implied-consequence failing). Aktobe C+
> (150.8 mm, 0.53% margin, steppe-aridity + half-year ratio, P_close borderline). **Infrastructure
> alert:** all 3 cite "previous 3-day record of 150.0 mm" — detection threshold used as prior
> record (`previous_record_year: null`); operator must verify authentic station records before
> publishing as "record-breaking." P9 6th cycle: all 3 use opener template + restate-math. P_close
> 9th cycle: 2 failing + 1 borderline. `gh` CLI absent (29th consecutive skip).
>
> **Jun 25: 5 fresh drafts (0% A-rate).** P_close 8th cycle: 3 failing (Taiz dust_event ×2 + Michigan monthly_low), 2 positive (Siberia fire "burns deep" + Barrow "nearly twice that total"). P_dust 3rd cycle: both Taiz dust_event drafts lack WHO anchor; all 4 dust_event corpus drafts template-converged. P9 5th precipitation_extreme (Barrow, same opener template + restate-math). First companion-fire peer comparison in fire corpus. "Roughly"/"nearly" hedges cost Barrow A-; date-baking ("today"/"same day") costs Siberia A-. `gh` CLI absent (28th consecutive skip).
>
> **Jun 24: 2 fresh drafts (0% A-rate).** Randolph UT monthly_high (B+): ecosystem specificity "normally blunts" = P_close 7th cycle failing (implied-consequence form). Al Aḥmadī Kuwait air_quality_hazard (B): 10.1× WHO ratio stated (P_dust POSITIVE), closes on system resolution "by evening" = P_close 7th cycle failing (resolution-close subtype). First air_quality_hazard in corpus. Draft [2] "June 24" date-baked — stale by Jun 26T14:50. Mediterranean SST `draft_20260622_171200_17` crosses 48h at ~Jun 24T17:12 UTC — operator must post/reject within ~2h of this run. `gh` CLI absent (27th consecutive skip).
>
> **Jun 23: 3 fresh drafts (33% A-rate).** Cope Rch TX all_time_high (A-): "push extremes fast" = declarative-consequence, P_close positive evidence. Columbus GA all_time_high (B): 1°F margin, dual-mechanism. Mediterranean SST regional_sst_anomaly (B): comparative-implied close + unexplained NOAA 2.5°C threshold (A3 filed). P_close 6th cycle: Columbus + Mediterranean = failing; Cope Rch = positive. `gh` CLI absent (26th consecutive staleness skip). Mediterranean SST "today" anchor → staleness at Jun 24T17:12Z.
>
> **Jun 22: 0 pending; 1 retroactive grade.** Barrow 7-day precip (draft_20260618_154318_15, created Jun 18T15:43Z, flagged ungraded in Jun 19/21) graded A-. "Has nowhere to go" = first precipitation_extreme declarative-consequence close — P_close positive evidence (validates the fix, not a failing observation). Restate-math confirmed: P9 now 3 cycles (all 3 precipitation_extreme corpus drafts). Queue empty 4th consecutive day. `gh` CLI absent (25th consecutive staleness skip).
>
> **Jun 21: 0 fresh drafts; queue empty.** No new drafts since Jun 18T15:43Z (~2.5d gap). P_new archived (2nd time): 3 consecutive fresh-draft cycles without cold-record (Jun 15/17/18) meets the 3+ runbook threshold. No new evidence for P_close/P9/P_dust/P5. `gh` CLI absent (24th consecutive staleness skip).
>
> **Jun 19: 0 fresh drafts; queue empty.** All 3 Jun 18 precipitation_extreme drafts operator-rejected (Barrow daily B+, Amsterdam B, Barrow 7-day [ungraded, created Jun 18T15:43Z]). First operator rejection of a B+ graded draft. No proposal evidence updates this cycle.
>
> **Jun 18: 2 fresh drafts (both precipitation_extreme, both B-range).** P_close 5th cycle confirmed (Barrow "any of it" + Amsterdam "stack up faster than they drain" both implied-consequence closes). New proposal P9 added (precipitation_extreme opener template convergence + restate-math). No dust/coral/cold-record drafts this cycle. The *source-health* sentinel (0.9.12.0+, every 4h) is a separate system.

**The agent does NOT implement code changes.** It accumulates evidence, sharpens proposals, and reorders priorities. The human operator decides what to actually ship and when.

> **Structural update (2026-06-16 eng-review).** This doc tracks voice quality
> toward the `>50%`-A-rate resumption bar. The 2026-06-16 `/plan-eng-review` found
> that bar is *structurally* unreachable as wired: it is graded by the
> daily-plan routine (dead since 2026-05-26), posting is paused until it clears
> (peak ever 21%), and A-grade drafts go stale in the queue before they could lift
> it. The **Throughput Initiative** addresses the structural causes directly —
> **Phase B** decouples the ship gate (per-draft critic-PASS + freshness instead of
> the dead cycle-level grader) and **Phase A** adds the missing per-stage kill-rate
> / critic-pass-rate instrumentation so "is voice the bottleneck or is the
> architecture?" becomes measurable rather than assumed. See
> [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md).
> The voice proposals below remain valid; they raise the A-rate at the source.

## Current state

| | |
|---|---|
| Bot commit | `0.9.108.1` per `main`'s `VERSION` file (unchanged since checked 2026-07-16). No new `main` commits touching `src/two_bot/prompts/writer_prompt.py` observed this session (rebase onto fresh `main` was a no-op — `main`'s tip is unchanged at `#449` since Jul 17's rebase). |
| Voice engine version | **two-bot + Attenborough/Economist voice + all-sources triage + evidence contract + diversity gate + automation dashboard** (Sonnet 4.6 writer prompt-cached + Gemini 2.5 Flash fact-checker [skips unknown kinds] + Gemini 2.5 Pro critic [assesses relative to available data]; all 23 sources on triage path via PR #150; evidence contract gates writer via 0.9.0.0; pending-type cap default 3 + per-type TTL sweep [fast 7d, coral/DHW 21d] via 0.9.6.0/0.9.16.0; `THEHEAT_TRIAGE_ENABLED=1` in CI; `THEHEAT_WRITER_SAMPLES=2` + `THEHEAT_CRITIC_REVISE_ENABLED=1` live since 2026-06-13; reganom enabled `manual_only` since 2026-06-27 [PR #347]; **2026-07-07 AM: "DETECTION PLUMBING IS NOT A FACT" writer rule + paired fact-check/critic gates [PR #386], dust bundles carry `who_pm10_multiple` [PR #386], `cyclone_land_threat` signal type [PR #388]; 2026-07-07 PM: precipitation "four moves" section bans restate-math + prescribes the annual-ratio anchor [PR #397], cyclone "four moves" section covers all 5 cyclone signal_kinds including the new `cyclone_landfall` [PR #404]**; routine beacon writes the `ROUTINE_BEACON` repo variable via `gh variable set` each cycle) |
| Last cycle A-rate | **25% (1/4, Jul 19)** — same rate as Jul 18, execution/signal-mix driven (3 of 4 fresh drafts `absolute_extreme`, all clean of P_tier, only 1 unstranded). 1 A-: Ahvaz, Iran `absolute_extreme`; 2 B+ (W Allis, Wisconsin `all_time_high`; Al Basrah, Iraq `absolute_extreme`); 1 B (Ahvaz/Bandar-E Mahshahr, Iran `absolute_extreme`). Prior: 25% (1/4, Jul 18); 80% (4/5, Jul 17); 100% (2/2, Jul 16, small-n); no fresh drafts Jul 15; 33% (1/3, Jul 14); no fresh drafts Jul 12–13; 0% (0/2, Jul 11); 33% (1/3, Jul 10); 50% (1/2, Jul 9, not a majority); 50% (4/8, Jul 8); 33% (2/6, Jul 7); no fresh drafts Jul 6; 20% (1/5, Jul 5); 20% (2/10, Jul 4); 33% (1/3, Jul 3); 0% (0/3, Jul 2); 0% (0/4, Jul 1); 22% (2/9 non-stale, Jun 30); 80% Jun 29 [BAR CLEARED]. |
| Resumption bar | majority A (>50%) sustained — **cleared Jun 29 (80%, n=5); Jun 30 returned 22%; Jul 1 0% (n=4); Jul 2 0% (n=3); Jul 3 33% (n=3); Jul 4 20% (n=10); Jul 5 20% (n=5); Jul 6 no fresh drafts; Jul 7 33% (n=6); Jul 8 50% (n=8, not a majority); Jul 9 50% (n=2, not a majority); Jul 10 33% (n=3); Jul 11 0% (n=2); Jul 12–13 no fresh drafts; Jul 14 33% (n=3); Jul 15 no fresh drafts; Jul 16 100% (n=2, small-n); Jul 17 80% (n=5) — cleared again, first n≥5 confirmation since Jun 29; Jul 18 25% (n=4); Jul 19 25% (n=4) — below bar 2nd consecutive cycle**. |
| Gap | **25 pp below bar** (50% − 25%, Jul 19, n=4). Same story as Jul 18: `absolute_extreme` dominates the fresh batch (3 of 4) and stays clean of P_tier every time, but P_close/A8-class softness (stranded declaratives, mechanism-only closes) caps 2 of the 3 at B+/B. P_close and P_compound remain the two highest-leverage *unimplemented* levers. **A8 now clears its promotion bar on both remaining axes** (stranded-mechanic: 2 instances; reused survivability-threshold clause: 3 instances) — moved to active proposals this cycle. |
| Posting | paused; operator decision pending — Jun 29 cleared bar (80%, n=5), Jul 16 cleared it again (100%, n=2, small-n), Jul 17 cleared it a 3rd time with the first large-n confirmation (80%, n=5), Jul 18–19 both fell back below bar at 25% (n=4 each) on the same signal-mix/execution pattern, not a regression in any shipped fix. Queue grew from 7 (Jul 18) to 9 (Jul 19) — 5 of 7 carry over unchanged, 2 Jul-17 `absolute_extreme` drafts dropped (cause unconfirmed), 4 fresh arrived. **0 strict staleness bulk-reject candidates this cycle** — 1 watch item (Ahvaz, forecast-date-elapsed under 48h). |
| Coverage | **638 cities × 180 countries** (was 613 × 179; +25 via PR #81) |
| Queue status | **9 pending as of Jul 19 grading** (up from Jul 18's 7): 5 carry-overs [Deaver WY `all_time_high` A- (Jul 17), Delhi `air_quality_hazard` B+ (Jul 18), Anchorage `precipitation_extreme` B (Jul 18), Astana `precipitation_extreme` B+ (Jul 18), Wausaukee WI `all_time_high` A- (Jul 18)]; 1 fresh A- [Ahvaz `absolute_extreme`]; 2 fresh B+ [W Allis `all_time_high`, Al Basrah `absolute_extreme`]; 1 fresh B [Ahvaz/Bandar-E Mahshahr `absolute_extreme`]. **2 Jul-17 `absolute_extreme` carry-overs dropped from the queue, cause unconfirmed** (Basrah B+, Al Basrah A- — the same recurring unexplained-contraction pattern). **0 strict staleness candidates this cycle**; 1 watch item (Ahvaz, forecast-date-elapsed but under 48h). Bot at 0.9.108.1 per `main`'s `VERSION`; `THEHEAT_WRITER_SAMPLES=2` + `THEHEAT_CRITIC_REVISE_ENABLED=1` live. **P_tier's tracking remains CLOSED** — all 3 fresh `absolute_extreme` drafts stayed clean this cycle, further confirming. |

## Active proposals

Ordered by leverage. Priority as of Jul 19: **P_dust, P9, and P_tier remain CONFIRMED, tracking
closed** — no re-opening needed; all 3 fresh `absolute_extreme` drafts this cycle stayed clean of
P_tier's banned form (further confirmation, not new tracking).
With all three shipped code fixes closed, the remaining *unimplemented* active proposals: **P_close**
(26 cycles, last evidence Jul 19: 1 positive [Ahvaz], 2 failing [Al Basrah, Ahvaz/Bandar-E
Mahshahr]) > **P_compound** (14 cycles, last evidence Jul 19: W Allis, standard double-qualifier,
overcome) > **A7** (per-location closing-construction reuse — not tested this cycle, no target-type
draft) > **A8 — newly promoted to active** (`absolute_extreme` opener-skeleton convergence +
stranded declarative clause + reused survivability-threshold clause: both remaining axes now past
the 2-instance promotion bar — see full write-up below) > **P5** (`absolute_extreme` self-selects
a real mechanic again via Ahvaz's idiom-flip closer). **A4, A5, and A6 not tested this cycle** (no
signal-kind-self-naming/cyclone/fire draft among today's 4 fresh drafts). **One operational item,
not a voice proposal:** 2 Jul-17 `absolute_extreme` carry-overs (Basrah, Al Basrah) dropped from
the queue this cycle, cause unconfirmed — same recurring pattern as the western Siberia fire
cluster's Jul 17→18 departure.
Each entry tracks: observation count (cycles where the failure mode appeared), last seen,
proposed fix, expected impact, status.

### ~~P1~~ — Era anchors parked at 1-in-10 — **SHIPPED 2026-04-29 (awaiting empirical confirmation)**

**Observed (cumulative):** 3 of 3 records used era anchors on Apr 25, 5 of 5 on Apr 27, 3 of 3 on Apr 29 — three consecutive cycles at 100%. User direction same day: park era anchors at no more than 1-in-10 tweets. Prose-only de-emphasis was insufficient; structural gate was required.

**Cycles observed:** Apr 25, Apr 27, Apr 29 (3 cycles, 100% deployment each).
**Last seen:** Apr 29.

**Implemented in same-day commit (voice engine v3):**

1. `_era_anchor_should_fire(seed_key, rate=0.1)` — deterministic 1-in-10 gate, seeded by city+year+date. Same draft cycle reproducible; across many seeds fires at ~10%.
2. `_era_anchor_hint` rewritten: 90% of calls return explicit "parked, not your turn" steer-away message naming the 5 alternative specificity vehicles. 10% of calls return curated content framed as "your 1-in-10 turn."
3. **Addendum-mismatch bug fixed.** `generate_all_time_record_tweet` was using `category="all_time_record"` but addenda were keyed `all_time_high`/`all_time_low` — addenda had been dormant. Fixed to `category=f"all_time_{kind}"`. Same fix for monthly. Added missing `monthly_low`, `country_low`, `record_low` addenda.
4. **5 record-type per-category addenda rewritten** to use a shared 6-vehicle specificity menu (`_RECORD_SPECIFICITY_VEHICLES` constant). Era anchor is option 6, explicitly marked PARKED.
5. **SYSTEM_PROMPT #1 ("HISTORICAL WEIGHT") rewritten** to be vehicle-agnostic. Was era-anchor-evangelizing ("anchor the year to something human"); now lists all 6 specificity vehicles equally and notes era anchors are parked.
6. **3 new bad-examples added:** explicit-gap math ("That gap is 4.5 degrees"), restate-padding ("The new high: X. The old one: Y."), era-anchor-then-restate template.

**Tests:** 23 era_anchor tests pass (up from 18 — added 5 gate tests). Full suite 566 passing.

**Status:** SHIPPED to `generator.py` — but `generator.py` was retired 2026-05-04. The
1-in-10 deterministic gate no longer runs. The two-bot writer has `memory.used_era_anchors`
tracking but no equivalent hard gate. Empirical confirmation of the gate rate is no longer
possible on the current code path. Whether era anchors are over-deployed in two-bot output
cannot be assessed until record drafts reach the pending queue. Move to Resolved when
operator confirms era-anchor logic is either ported to writer_prompt.py or unnecessary.

### ~~P1~~ — Fix station-name normalization: fact_check kills on GHCN suffix labels — **SHIPPED 2026-05-12 (PR #82)**

**Observed:** 2026-05-12 — "Paddock Lake 4 Ne" (Wisconsin) and "Sioux City Ang" (Iowa)
both produce BUNDLE_FACT kills every run because `normalize_station_name()` strips the
direction/distance suffix before the writer sees the bundle, but the raw suffix survives
in bundle fields the fact-checker validates against. Pattern fires three times today on
the same station (once per alerts run). Also observed 2026-05-11 on Sioux City Ang.

**Cycles observed:** May 11, May 12 (2 grading cycles; 5+ individual fact-check kills).
**Last seen:** 2026-05-12.

**Resolution:** Root cause was inside `normalize_station_name` itself, not bundle-builder
plumbing. `_COOP_SUFFIX_RE` required adjacent digit+direction (`1SW`) and missed
space-separated (`4 NE`). Fixed with `\s*` between digit and direction. Plus new
`_MILITARY_SUFFIX_RE = r"\s+ANG$"` for the Air National Guard class (covers Sioux City
ANG). Two regression tests in `tests/test_ghcn.py` cover both failure modes.

**Status:** SHIPPED in PR #82 (`48ee110`). Awaiting empirical confirmation on the next
alerts run that BUNDLE_FACT kills on these stations stop firing.

### ~~P2~~ — Fix fire MW rounding: fact_check kills on decimal truncation — **SHIPPED 2026-05-12 (PR #80)**

**Observed:** 2026-05-11-12 — fact-checker kills fire drafts when writer rounds FRP
values: 480.34 → 480 (BUNDLE_FACT), 547.92 → 548 (BUNDLE_FACT), 301.55 → 301
(BUNDLE_FACT). The fact-checker requires exact numerical match. Also observed: a
fabricated Hoover Dam comparison killed as WORLD_KNOWLEDGE ("roughly what the Hoover Dam
generates" for a 301 MW fire; Hoover ≈ 2,080 MW — off by factor 7). Two separate issues.

**Cycles observed:** May 11, May 12 (2 cycles; multiple kills each).
**Last seen:** 2026-05-12.

**Correction (2026-05-12, post-Codex-review):** the prior version of this plan proposed
telling the writer to round FRP to one decimal and claimed "the fact-checker requires an
exact match within 0.5 MW." Codex's review caught the contradiction:
`src/two_bot/prompts/fact_check_prompt.py` line 9 says *"Verify exact match (number, unit,
date). Mismatches = failure."* — there is **no tolerance rule**. Telling the writer to
emit `480.3 MW` when the bundle carries `480.34` would still BUNDLE_FACT-kill. The fix
has to make the writer's number match the bundle's number exactly, or change the bundle,
or change the fact-checker. Pick one — don't paper over it with a tolerance claim that
the runtime doesn't honor.

**Proposed fix (a — rounding, REVISED):** Round at the **bundle builder**, not at the
writer. In `src/two_bot/intern.py:build_fire_bundle` (line 167), change
`"value": fire.frp` to `"value": round(fire.frp, 1)` (and the same in `raw_signal_dump`
at line 180). The bundle then carries `480.3` as the source of truth; the writer
naturally echoes `480.3 MW`; the fact-checker confirms exact match. No prompt rule
needed, no fact-checker mutation needed, no runtime tolerance bookkeeping. Add a
regression test in `tests/two_bot/test_intern.py` that asserts the FRP `value` field is
rounded to 1 decimal for representative inputs (480.34 → 480.3, 547.92 → 547.9,
301.55 → 301.5 or 301.6 per Python banker's rounding).

  **Why bundle-side rounding wins over the alternatives:**
  - **vs. writer-side rule:** Writer-side rules are fragile under model stochasticity
    (see #76's length-cap retry). The bundle is source-of-truth and never drifts.
  - **vs. fact-check tolerance:** Adding a `±0.5 MW` tolerance to the fact-check prompt
    would mutate runtime behavior, require new voice-regression validation, and
    introduce a soft-equality rule that downstream code may not honor identically. The
    bundle-side fix preserves the "exact match" doctrine cleanly.

**Proposed fix (b — fabrication, unchanged):** Add to the writer prompt's HARD RULES /
bad-examples list: "Do NOT compare fire FRP to a named power plant or dam unless the
comparison's exact MW is provided in the bundle. 'Roughly what [named plant] produces'
is hallucination territory. Observed failure modes: Hoover Dam at full capacity (~2,080
MW) applied to a 301 MW fire; Akosombo Dam at full capacity (~1,020 MW) applied to a
361 MW fire." (This is already partially landed in PR #74's "no self-supplied facility
MW" rule; verify the wording still covers FRP-specifically and tighten if it doesn't.)

**Expected impact:** Bundle-side rounding unlocks every fire draft that's currently
dying on float-precision mismatch. The fabrication rule (already largely in place via
#74) prevents the Hoover/Akosombo class entirely.

**Status:** SHIPPED in PR #80 (`4677869`). Bundle-side rounding in
`src/two_bot/intern.py:build_fire_bundle` — both `headline_metric.value` and
`raw_signal_dump.frp` use `round(fire.frp, 1)`. Five-case regression test in
`tests/two_bot/test_intern.py::test_build_fire_bundle_rounds_frp_to_one_decimal` covers
the three production failures (480.34, 547.92, 301.55) plus banker's-rounding edges.
The writer-prompt no-self-supplied-facility-MW rule landed in PR #74 and remains in
force. **Empirically confirmed: 2 graded cycles (May 13, May 14) with 6 fire drafts
total, all producing clean 1-decimal FRP values (309.6, 364.7, 307.6 MW), zero
BUNDLE_FACT rounding kills observed.**

### ~~P3~~ — Writer fire overcall: add seasonal/calendar context as a verifiable framing — **SHIPPED 2026-05-12 (PR #84)**

**Observed:** 2026-05-11-12 — writer kills fire drafts citing "no historical_context
available; no peer comparison confident enough to use; no verifiable seasonal or rarity
framing without archive data." Two Western Sahel fires (480 MW, 301 MW) and one Siberia
fire (548 MW) died on this basis. The writer knows seasonal context exists ("May fires
in Amur are seasonally plausible") but won't use it without verified archive data.
The old voice engine used seasonal deadpan as world knowledge without archive backing.

**Cycles observed:** May 11, May 12 (2 cycles; 3+ writer self-kills per cycle).
**Last seen:** 2026-05-12.
**Proposed fix:** Add to `src/two_bot/prompts/writer_prompt.py` fire framing section:
"Seasonal and calendar context is world knowledge — it does not require archive data.
'The burning season in [region] typically peaks in [month].' or 'Fire activity here
normally fades by [month]. It is [current month].' are always verifiable framings. Do
NOT self-kill a fire draft solely because no numeric historical comparison is available.
When the only context is seasonal, use it. That's enough."

**Expected impact:** Unlocks the class of fire drafts where seasonal deadpan is the
mechanic. Sahel and Siberia fires are consistently in this class. One paragraph addition;
no other changes needed.

**Resolution:** Two changes to `src/two_bot/prompts/writer_prompt.py`:
1. Removed the "[country]'s fire/storm/wet season peaks in [month]" bullet from the
   `historical_context=empty` "do NOT write" list. The HARD RULES `NO FABRICATED
   CONTEXT` rule (with its 95%+ confidence gate) still catches truly invented seasonal
   claims; the removed bullet over-banned well-established geography.
2. Added a "Seasonal context for fires is world knowledge" paragraph after the existing
   "Important: lack of historical_context does NOT automatically mean kill" guidance.
   Emphasizes integrating seasonal framing INSIDE the system clause (the wink-kicker
   rules still apply — no separate calendar-stamp closer).

The proposal's second example ("Fire activity here normally fades by [month]. It is
[current month].") was trimmed during implementation because the second sentence
matched the banned wink-kicker shape from line 80. Replaced with single-clause example
("the Sahel dry season runs December–March") and explicit guidance against the calendar
closer.

**Status:** SHIPPED in PR #84. **Empirically confirmed: 2 graded cycles (May 13, May 14)
with 6 fire drafts (Mali, Campeche, Mongolia x 2 cycles), all reaching pending with
seasonal framing deployed. Zero P3 self-kills observed across both cycles. Failure mode
closed in two-bot pipeline.**

### ~~P4~~ — Add Wodehouse rule to top of writer_prompt.py — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** humor-lens evaluation (Apr 27 corpus) found Wodehouse-rule violations are
the single most predictive failure mode across all corpus cycles. Drafts that try too
hard graded D-/C+/B regardless of mechanics; drafts that don't try graded B+/A-
regardless. Apr 29 [2] Mexico City repeated the explicit-gap-math violation. Two
consecutive prior cycles with the same violation. **2026-05-12 update:** Andrew's
explicit voice direction on Mankato manual-editorial reject names the same pattern:
"defensive 'A record is a record' closer" — the two-bot Sonnet writer reproduces
Wodehouse violations. Evidence confirmed in new two-bot pipeline.

**Cycles observed:** Apr 24, Apr 25, Apr 27, Apr 29, May 12 (5 cycles; most consistent
failure mode in the corpus).
**Last seen:** 2026-05-12.
**Proposed fix (REDIRECTED to two-bot):** Add as rule #0 in
`src/two_bot/prompts/writer_prompt.py` before the structural rules:

> 0. **DON'T SOUND LIKE YOU'RE TRYING.** The data is already extraordinary; the voice
> is its straight man. The Wodehouse rule: trying too hard breaks the spell. Signals
> of effort: approximation when exact is available ("nearly 3 degrees" when it's 2.7F),
> restate-padding ("The new high: 94.5F. The old one: 93.7F." after the data was given),
> poetry-attempt closers ("pointed at the sky"), defensive justification ("a record is
> a record") — all show effort, all kill the tweet before it lands.

**Expected impact:** Highest-leverage prompt change in the proposal stack. Wodehouse
violations cluster across grades and pipelines. Eliminating them moves B drafts to
B+/A- without changing structure.

**Resolution:** New section `# THE WODEHOUSE RULE` added to
`src/two_bot/prompts/writer_prompt.py` directly before `# HARD RULES`. Names the
four effort-signal failure modes (approximation, restate-padding, poetry-attempt
closers, defensive justification) and ties them back to the Attenborough/Economist
voice anchor — "the data is already extraordinary; the voice is its straight man."
Bundled with two other quality moves in the same PR:
1. **FRP intensity tier** in `build_fire_bundle` (`frp_tier` + `frp_tier_floor_mw`
   in `current_facts`) so the writer can give readers a scale-word ("high-intensity"
   at 309 MW) instead of opaque raw megawatts.
2. **Category cooldown** via new `recent_categories` field on `MemorySlice`. 24h
   per-category dedup prevents the "two fires in a row" pacing failure Andrew
   flagged on 2026-05-12 when both pending drafts were Sahel-style fires.

**Status:** SHIPPED in PR #85 / PR #89. **Empirically confirmed (partially): 2 graded
cycles (May 13, May 14) with 9 two-bot drafts total — zero Wodehouse violations observed
in either cycle. Fire drafts arrive clean; no defensive closers, no explicit gap math,
no restate-padding. A-rate has not lifted yet; Wodehouse violations were not the current
bottleneck — named mechanics and category-specific convergence are.**

### P_close — Mechanism close defaults to implied consequence rather than declarative statement

**Observed:** 2026-06-07 — Barrow, Alaska precipitation_extreme, B+: "sheets across the
surface instead" — consequence implied by contrast ("instead"), not named. 2026-06-10 —
Chesnee, South Carolina monthly_low, B+ (status=approved): "threaten gardens well into
early summer" — frost implied, not stated. 2026-06-13 — Red Dog Mine, Alaska monthly_low,
C+: "tundra terrain offers no shelter from cold air pooling on clear nights" — mechanism
explanation only; no consequence named or implied (the coldest version: stops at mechanism
before reaching even the implied-consequence stage). Three consecutive fresh-draft cycles
from different signal categories (precipitation_extreme, monthly_low ×2), same gap to A-.

All three had correct mechanism identification (ecosystem specificity operating). The gap
is in the LANDING: the writer arrives at the physical mechanism but stops before naming
what the mechanism does. The corpus A-grade closers state the consequence flatly:
"persistence is what kills" (Madagascar), "nowhere to drain" (Costa Rica), "It is April"
(Mali). None defer to implication; none stop at mechanism.

**Cycles observed:** 11 active (Jun 7 pending; Jun 10 approved voice observation; Jun 13 Red Dog Mine;
Jun 15 retroactive; Jun 18 Barrow + Amsterdam; Jun 23 Columbus GA + Mediterranean SST failing,
Cope Rch TX positive; Jun 24 Randolph UT + Al Aḥmadī Kuwait both failing; Jun 25 Taiz ×2 +
Michigan monthly_low failing, Siberia fire + Barrow precip positive; Jun 26 Amsterdam
implied-consequence failing + Anchorage mechanism-only failing + Aktobe half-year ratio
borderline; Jun 28 — Taiz [3] mechanism-only failing, Mediterranean [4] "nowhere fast to go"
borderline positive, Beaver Dams [6] "blunt the afternoon peak" implied-consequence failing,
Casper [7] "what June air masses would otherwise deliver" implied-consequence failing;
Astana [5] steppe-closer = ecosystem-incongruity punchline, not traditional P_close;
Jun 29 — marine_heatwave [2] "floor of a new streak" positive, France reganom [3] "hour by hour" failing,
Congo fire [4] "convective lid" positive, Prudhoe Bay [5] latitude-peer n/a, Amsterdam [6] "nowhere for the water to go" positive).
Jun 15 retroactive: 5 A- drafts (Loxahatchee NWR, Beaver Dams, Kapingamarangi, Gilbert Islands,
Chesnee SC) each reached A- not A — consistent with P_close pattern (implied consequence or
mechanism-only close). Loxahatchee: "water levels are still dropping" implies drought, doesn't
name it. Beaver Dams: "stranding paddlers well into spring" implies low water, names the human
consequence (strong A- form, closest to A). Kapingamarangi/Gilbert Islands/Chesnee: similar
implied-consequence structure. Nauru (A): "no adjacent reef system to reseed it" — declarative
structural consequence, no hedge. Validates P_close gap: Nauru's direct form earns A; the A-
drafts stop one step short.
Jun 24: Randolph UT monthly_high B+ ("normally blunts the heat" = implied-consequence form; new
signal type confirms cross-category scope). Al Aḥmadī Kuwait air_quality_hazard B ("before sea
breezes suppress them by evening" = resolution-close subtype — close actively defuses the
violation by naming the system's natural recovery, not just implying consequence). P_close now
confirmed across 7 signal types: precipitation_extreme, monthly_low, coral, fire, all_time_high,
monthly_high, air_quality_hazard.
Jun 25: Siberia fire B+ ("burns deep" = declarative-consequence, peatland-carbon close, P_close
POSITIVE). Barrow AK B+ ("delivered nearly twice that total" = declarative annual-ratio, P_close
POSITIVE). Michigan monthly_low B ("cold air finds less land friction to slow it down" = mechanism-
only, failing). Taiz Jun 24 C+ ("pushing it into the terrain" = weakest mechanism close in corpus,
failing). Taiz Jun 25 B- ("push it upslope into the city basin" = transport mechanism, failing).
P_close now confirmed across 8 signal types (adding dust_event to the prior 7).
Jun 26: Amsterdam C+ ("not to absorb a month's rain in 72 hours" = implied-consequence, failing).
Anchorage B ("wring out moisture in compressed bursts" = mechanism-only, failing — weakest form).
Aktobe C+ ("three days here matched half a year's average" = declarative ratio, borderline — correct
form, setup too thin at 0.53% margin + "just edging" hedge). P_close now confirmed across 9 signal
types via Jun 26 (precipitation_extreme ×3 same cycle).
Jun 28: Mediterranean SST [4] B+ ("heat absorbed at the surface has nowhere fast to go" —
borderline positive; "fast" hedges slightly, compare Costa Rica A- "nowhere to drain"). Taiz
dust_event [3] C+ (mechanism-only, failing). Beaver Dams all_time_high [6] B+ ("little moisture
overhead to blunt the afternoon peak" = negation-of-blunter = implied, failing). Casper monthly_low
[7] B ("pushing lows well below what June air masses would otherwise deliver" = implied-consequence
framed as comparative, failing). Astana [5] steppe-incongruity close is not P_close territory.
P_close now confirmed across 10 signal types (adding regional_sst_anomaly via Mediterranean [4]).
Jun 29: marine_heatwave [2] A- ("a record set two years ago is already the floor of a new streak" =
declarative floor/ceiling reframe, POSITIVE). France reganom [3] B+ ("the heat debt compounds hour
by hour" = implied-consequence metaphor, failing). Congo fire [4] A- ("something has broken the
convective lid" = declarative physical consequence, POSITIVE). Prudhoe Bay [5] A- (latitude
peer-comparison close — not P_close territory; n/a). Amsterdam [6] A- ("there is nowhere for the
water to go" = declarative consequence, POSITIVE). P_close now confirmed across 11 signal types
(adding marine_heatwave [2] and regional_anomaly/reganom [3] via Jun 29).
Jul 1: Basrah, Iraq absolute_extreme [11] B ("offers no evaporative relief when the land is
already this hot" = declarative named-absence consequence, POSITIVE — first absolute_extreme
P_close observation). Morrill Fire, Nebraska fire_footprint [12] B ("the underlying sand can
begin to shift" = forward-looking declarative physical consequence, POSITIVE — first
fire_footprint P_close observation, close to Nauru-tier form). Al Baṣrah al Qadīmah, Iraq
absolute_extreme [13] B- ("recycles heat back into an already superheated air column" =
describes an ongoing state, not a forward consequence — mechanism-only, failing). Wadi Halfa,
Sudan dust_event [14] C+ ("dampens the column" = resolution/dispersal close, same subtype as
Al Aḥmadī Kuwait's "by evening" — failing). P_close now confirmed across 13 signal types
(adding absolute_extreme and fire_footprint via Jul 1).
Jul 2: Ft Green, Florida all_time_high [15] B ("the lid lifts fast" — names a physical event
[the heat cap failing] but stays metaphorical/abstract rather than a plain declarative
consequence, closer in kind to Congo fire's A- "broken convective lid" than to a mechanism-only
close — BORDERLINE positive). Basrah, Iraq absolute_extreme [16] B ("no terrain to break the
dry continental air mass that builds" = declarative named-absence consequence, same family as
[11]'s "no evaporative relief," POSITIVE). Ft Green, Florida all_time_high [17] C+ ("days that
beat 102°F have overcome that convective ceiling" — restates the headline number instead of
adding a consequence, confusing self-referential framing, FAILING). 3rd consecutive cycle with
both positive and failing instances in the same batch — the gap is stable, not closing on its own.
Jul 3: Canadian Arctic fire [18] A- ("reaches carbon the frozen ground has held for millennia" =
declarative carbon-release consequence, POSITIVE — 3rd instance of this specific fire mechanic
after Jun 25 Siberia "burns deep" and Jun 29 Congo fire's convective-lid close; strongest
execution of the three). Near-duplicate Canadian Arctic fire [19] B+ (same signal, "burns into
organic soil layers that took centuries to accumulate" = declarative, POSITIVE but weaker —
"centuries" vs. [18]'s "millennia," "organic soil layers" vs. [18]'s "carbon," which ties
directly to climate-feedback stakes). Typhoon Bavi [20] C+ — not P_close territory in the
positive sense: "Bavi crossed it by nearly double" is a ratio restatement, not a named
consequence, and the sentence it's built on is itself a P_tier violation (see P_tier). First
`cyclone_rapid_intensification` P_close observation: negative/n/a, not failing in the usual
implied-consequence sense — the draft simply never reaches for a consequence at all. P_close now
confirmed across 14 signal types (adding `fire` via [18]/[19]'s carbon-release form, which is
distinct from Jun 25's first fire P_close instance only in being the 2nd/3rd confirmation, not a
new type).
Jul 4: **First clean `cyclone_rapid_intensification` P_close-positive instance.** Typhoon Bavi's
2nd corpus draft ("storms that cross it in July can intensify faster than forecasters or ships
can react") names a genuine stakes-consequence, unlike Jul 3's ratio-only instance — the first
time this signal type reaches the positive form. Loxahatchee FL all_time_high A- ("the column
runs free" — declarative capping-mechanism failure, same family as Congo fire's "broken
convective lid"). Al Başrah al Qadīmah absolute_extreme B ("little maritime relief" —
named-absence form, positive, but capped at B by P_tier regardless — see P_tier). 3 positive
total. 6 failing: Island Pond VT ("can just as easily trap heat" — conditional/hedged, weaker
than mechanism-only); Barrow AK ("rain sheets across frozen ground rather than soaking in" —
mechanism-only, no stated downstream consequence, same gap as every prior Barrow instance);
Astana ("annual rainfall averages roughly 300 mm total" — a new low-water mark: a bare
comparative fact with no causal mechanism or consequence at all, the weakest close form observed
to date, while sitting on the batch's best unstated joke); Basrah absolute_extreme ("loads the
air before continental heat arrives" — mechanism-sequencing only); Rocky Mountains CO fire
("intensity scales fast" — vague velocity closer, same class as the mid-latitude fire ceiling);
Urumqi dust_event ("topographic containment does the rest" — resolution-form, same as prior
dust_event closes). P_close now confirmed across 14 signal types (unchanged — no new type this
cycle; `cyclone_rapid_intensification`'s positive instance is the 2nd confirmation of an
already-counted type, not a new one).
Jul 5: eastern Siberia fire A- ("doesn't just burn the surface — it thaws the ground beneath
it" = declarative physical consequence, POSITIVE — 4th corpus instance of the
permafrost-carbon fire mechanic, all 4 grading B+ or A-, the single most reliable A-grade
path for `fire` in the corpus). Doha, Qatar absolute_extreme ("closing off the evaporative
cooling that makes extreme dry heat survivable" = declarative survivability-mechanism
statement, POSITIVE — the sharpest `absolute_extreme` close yet, still capped at B by
P_tier). Johannesburg air_quality_hazard ("concentrating it through the day" = accumulation
trajectory, not a named consequence — FAILING, same resolution/trajectory subtype as Jun
24's Al Aḥmadī "by evening"). Phalodi dust_event ("wash the column clean" = resolution-form,
FAILING, same subtype as every prior dust_event close). Urumqi dust_event, 3rd instance
("the topography traps it" = resolution-form, FAILING, near-verbatim repeat of its own prior
two closes). P_close now confirmed across 14 signal types (unchanged — no new type this
cycle).
**Last seen:** Jul 5 (2 positive, 3 failing).
Jul 7: Snowshoe, West Virginia all_time_high A- ("89°F is the kind of reading the valley
floor expects, not the ridge" = declarative elevation-inversion incongruity, POSITIVE —
names the displacement directly rather than implying it). Soweto, South Africa
air_quality_hazard A- ("have nowhere to vent" = declarative named-absence consequence,
POSITIVE — same family as Costa Rica's "nowhere to drain" and Amsterdam's "nowhere for the
water to go," both A-; first `air_quality_hazard` corpus draft to land this form, and the
first A-grade for the type). Ahvaz, Iran absolute_extreme B ("no relief from elevation or
sea" = declarative named-absence, POSITIVE, but capped at B by the pre-fix P_tier
violation). **First `record` (day-of-year record) corpus draft: Aibonito, Puerto Rico B**
("its elevation keeps it cooler than the lowland coast, which makes records there harder to
set and longer-lasting" = expository context explaining rarity, never reaches a stated
consequence — mechanism-only/expository, FAILING on its first appearance, same pattern as
every other type's debut). Riyadh, Saudi Arabia air_quality_hazard B ("suppresses mixing and
traps fine particles close to the surface" = mechanism-only, FAILING). P_close now confirmed
across 15 signal types (adding `record` via Aibonito).
**Last seen:** Jul 7 (3 positive: Snowshoe, Soweto, Ahvaz [capped at B by P_tier
regardless of close quality]; 3 failing: Zaragoza, Aibonito, Riyadh).
Jul 8: 4 positive — Barrow AK precipitation_extreme ("one storm just delivered
two-thirds of a normal year in a day" = declarative annual-ratio consequence, POSITIVE,
first fully clean precipitation_extreme draft in corpus history); Astana precipitation_extreme
("this single storm delivered roughly a sixth of a typical year's rain" = same declarative
ratio form, POSITIVE); Anchorage precipitation_extreme ("compressing what would otherwise be
weeks of accumulation into days" = declarative physical-transformation consequence, POSITIVE,
the batch's best-constructed close); Riyadh air_quality_hazard ("this is a basin-scale loading,
not a street-corner spike" = a new subtype — declarative scale-honesty contrast, distinct from
the corpus's prior named-absence/incongruity POSITIVE forms, POSITIVE). 4 failing: Snowshoe
all_time_high ("that elevation normally keeps summer highs well below what the valleys see" =
implied-consequence, FAILING — notably weaker than this same station's Jul 7 A- draft, which
stated the same inversion declaratively one day earlier); Riyadh dust_event ("both source
regions feed the same column" = mechanism-only, FAILING — the P_dust WHO-anchor fix landed
clean on this same draft, confirming the two proposals are orthogonal); Typhoon Bavi
`cyclone_land_threat` ("directly in the Western Pacific typhoon corridor" = expository, not
even mechanism-only, FAILING on its first corpus appearance — same debut pattern as every
other signal type). **New type, POSITIVE on debut:** Typhoon Bavi `cyclone_landfall`
("sustain major typhoon strength almost to the coast" = declarative causal statement, POSITIVE
— the first signal type since Congo fire/Prudhoe Bay [Jun 29] to land POSITIVE on its very
first corpus instance rather than debuting FAILING). P_close now confirmed across 17 signal
types (adding `cyclone_landfall` [positive] and `cyclone_land_threat` [failing] via Jul 8).
**Last seen:** Jul 8 (4 positive: Barrow, Astana, Anchorage, Riyadh air_quality_hazard; 4
failing: Snowshoe, Riyadh dust_event, Typhoon Bavi `cyclone_land_threat`; Typhoon Bavi
`cyclone_landfall` also positive, counted above).
Jul 9: 1 positive — Stevensville, Maryland `all_time_high` ("low terrain and Atlantic
moisture normally blunt the worst of continental heat; that buffer failed" = declarative
buffer-failure consequence, POSITIVE, same shape as Jun 29's Congo fire A-). 1 failing —
Anchorage, Alaska `precipitation_extreme` ("wring out moisture in concentrated bursts" =
mechanism-only, FAILING — one word from Jun 26's own Anchorage draft, "wring out
moisture in compressed bursts," and a materially weaker close than this same station's
Jul 8 A- draft on a different bundle metric two days earlier).
**Last seen:** Jul 9 (1 positive: Stevensville; 1 failing: Anchorage).
Jul 10: 1 positive — Ahvaz, Iran `absolute_extreme` ("where shade and rest alone stop being
enough" = declarative survivability-consequence, POSITIVE — one of the strongest closes of
this signal type; no longer P_tier-capped, see that entry, so this is also the first
A-grade `absolute_extreme` draft in the corpus). 2 short of positive: Riyadh, Saudi Arabia
`dust_event` ("Riyadh sits directly in that corridor" = structural/locational, not a named
consequence — BORDERLINE, avoids the resolution/dispersal anti-climax that dominated
pre-fix `dust_event` closes but still stops short of a declarative form); Tepee Creek,
Montana `all_time_high` ("continental heat rarely arrives intact this far into the
Rockies" = implied form, states the norm but never declares it broke this time — FAILING).
P_close now confirmed across 17 signal types (unchanged — no new type this cycle).
**Last seen:** Jul 10 (1 positive: Ahvaz; 1 borderline: Riyadh; 1 failing: Tepee Creek).
Jul 11: 2 positive, both weak-declarative form. Interior Alaska fire ("burns into the
organic layer above the frozen ground" — states the fire's action directly, consuming
ancient carbon storage, not merely a mechanism; same tier as Jul 3's near-dup, weaker than
Jul 3's original A- and Jul 5's A- because no specific carbon/climate stake or state-change
is named beyond the physical extent of the burn). Western Siberia fire, 3-signal cluster
("burning across peat that took centuries to accumulate" — same class of consequence as
Jul 3's near-dup close, consistent with that precedent's grading). Both instances reuse a
prior corpus draft's phrasing near-verbatim on a different fire event — see new proposal
A6 below; the P_close call itself is unaffected (both count as positive, same as the
precedent they echo), but the repetition is worth watching as a separate quality axis. No
new signal type. P_close now confirmed across 17 signal types (unchanged).
**Last seen (pre-Jul-14):** Jul 11 (2 positive: interior Alaska, western Siberia; both
weak-declarative form).
Jul 14: 1 positive — Basrah, Iraq `absolute_extreme` ("removes the ceiling" = declarative
physical-mechanism consequence, POSITIVE, same family as Congo fire's "broken convective
lid" and this cycle's own Stevensville carry-over "that buffer failed"; also now clear of
the P_tier cap that suppressed every prior Basra-area draft's grade regardless of close
quality — see P_tier). 1 failing — Randolph, Utah `all_time_high` ("high-desert elevation
normally bleeds off the heat that pools across the Great Basin floor" = implied-consequence
form, states the general norm but never declares the buffer failed this time; near-verbatim
echo of this same city's own Jun 24 `monthly_high` draft's "normally blunts the heat" — see
new proposal A7). Ontario, Canada `fire` cluster is not P_close territory in either
direction: the draft never reaches for a mechanism or consequence at all (see P5) — logged
as a P5 counter-instance, not a P_close observation. P_close now confirmed across 17 signal
types (unchanged — no new type this cycle).
**Last seen (pre-Jul-16):** Jul 14 (1 positive: Basrah; 1 failing: Randolph).
Jul 16: 2 positive, 0 failing — the first clean sweep since Jul 8's 4/4. Powderville,
Montana `all_time_high` ("no marine layer and no terrain to interrupt heat building across
the open steppe" = declarative named-absence consequence, POSITIVE — same family as
Basrah's "offers no evaporative relief"/"no terrain to break the dry continental air mass,"
the 3rd `all_time_high` instance of this specific named-absence-continental-interior form).
Oslo `hot10` ("is what a warmer baseline looks like at high latitudes" = declarative
accelerating-warming reframe, POSITIVE — 2nd corpus instance of the interpretive-reframe
subtype after Jun 29's marine_heatwave "already the floor of a new streak," and the first
`hot10` P_close observation in the corpus, positive on debut). P_close now confirmed across
18 signal types (adding `hot10`).
Jul 17: Bandar-E Mahshahr, Iran `absolute_extreme` ("the air has nowhere to cool" = declarative
named-absence consequence, POSITIVE — same family as Basrah's "no evaporative relief").
Deaver, Wyoming `all_time_high` ("the terrain that blocks moisture also traps heat" =
declarative verb-phrase consequence, POSITIVE — "traps heat" passes the ≤5-word verb-phrase
test directly). Al Basrah, Iraq `absolute_extreme` ("outdoor survival becomes genuinely
contested" = declarative global-superlative stakes statement, POSITIVE — the batch's strongest
form, no hedge). Tunis `hot10` ("heat this far from seasonal average has stopped arriving one
city at a time" = declarative systemic-consequence reframe, POSITIVE — a new leaderboard-
aggregate variant of the interpretive-reframe subtype Oslo debuted Jul 16, this time describing
the whole 10-city cohort rather than a single peer comparison). Basrah, Iraq `absolute_extreme`
FAILING, but with a new wrinkle: the draft's one genuinely declarative clause ("shade and
stillness stop being enough") exists but is stranded mid-sentence-1 as a qualifier rather than
placed in the closer; the actual close ("the wet-bulb load here is rarely what the dry number
suggests") is hedged ("rarely") and describes data-interpretation uncertainty, not a named
physical consequence — a **stranded-mechanic** failure mode distinct from this proposal's usual
implied-vs-declarative gap (the declarative move is present in the draft, just misplaced). 4
positive, 1 failing — the best positive-to-failing ratio in a single cycle since this proposal
was filed.
**Last seen (pre-Jul-18):** Jul 17 (4 positive: Bandar-E Mahshahr, Deaver WY, Al Basrah, Tunis; 1
failing: Basrah — stranded mechanic).
Jul 18: Wausaukee, Wisconsin `all_time_high` ("without the lake bleeding it off first" =
declarative named-absence mechanism-failure, POSITIVE — same family as Basrah's "no evaporative
relief"/Powderville's "no terrain to interrupt heat building"). Delhi, India `air_quality_hazard`
("the seasonal scour isn't keeping up" — a genuine judgment call: reads as a declarative
process-failure statement structurally similar to the named-absence positives above, but graded
conservatively as FAILING to stay consistent with this signal type's established precedent
[Johannesburg's "concentrating it through the day," Al Aḥmadī's "before sea breezes suppress them
by evening"], since it names a failing mechanism rather than a downstream consequence for a
reader; flagged explicitly as the strongest `air_quality_hazard` device yet and worth a second
opinion on whether the FAILING call is still correct as this signal type's mechanics mature).
Astana, Kazakhstan `precipitation_extreme` (the companion-city + annual-baseline-contrast close,
"three cities delivered a sixth of that at once," is structurally the declarative form this
proposal has been asking `precipitation_extreme` drafts to reach for since P9's own fix shipped —
but the arithmetic is ambiguous per-city vs. combined, so graded partial/positive-with-caveat
rather than a clean POSITIVE). Anchorage, Alaska `precipitation_extreme` ("compress moisture into
short, intense bursts" = mechanism-only, FAILING — the 3rd instance of this station's own
recurring phrase family, see new active proposal A7). P_close now confirmed across 18 signal
types (unchanged — no new type this cycle; today's 4 drafts are all previously-confirmed types).
**Last seen (pre-Jul-19):** Jul 18 (1 positive: Wausaukee; 1 conservatively-failing: Delhi; 1
partial/ambiguous: Astana; 1 failing: Anchorage).
Jul 19: Ahvaz, Iran `absolute_extreme` ("shade is infrastructure, not comfort" = declarative
idiom-flip, POSITIVE — a fresh construction, not a variant of A8's tracked survivability-threshold
clause family, and correctly placed as the tweet's actual closer). Al Basrah, Iraq
`absolute_extreme` — a 2nd instance of the exact **stranded-mechanic** shape Jul 17's Basrah
introduced: a genuinely declarative line ("shade, hydration, and rest stop being adequate
buffers") is buried mid-sentence-1 rather than placed in the closer, while the actual close ("Nearby
Basrah is forecast to hit 50.6°C the same day") is a bare, non-declarative peer-comparison fact —
FAILING on closer-position grounds despite the real declarative move existing elsewhere in the
draft. Ahvaz/Bandar-E Mahshahr, Iran `absolute_extreme` ("Shallow Gulf waters add humidity to
desert heat that is already among the highest on Earth" = mechanism-only, FAILING — explains a
contributing factor without naming a consequence). P_close now confirmed across 18 signal types
(unchanged — no new type this cycle).
**Last seen:** Jul 19 (1 positive: Ahvaz; 2 failing: Al Basrah [stranded-mechanic], Ahvaz/Bandar-E
Mahshahr [mechanism-only]).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
in the system-clause / second-sentence guidance section (near the "delete the system clause"
test already present from PR #85):

> When the second sentence closes on a mechanism, name the consequence directly — don't
> imply it, and don't stop at the mechanism. "Drain heat fast enough to frost gardens in
> June" beats "threaten gardens well into early summer." "Rain sheets across the surface"
> beats "sheets across the surface instead." "Cold pools here on clear nights, breaking
> June records" beats "tundra terrain offers no shelter from cold air pooling." The
> consequence lands in ≤5 words. Test: can you state it as a verb phrase (frost / flood /
> strand / kill / pool / fail)? If yes, do it. Mechanism without consequence is the C form;
> implied consequence is the B+ form; declarative consequence is the A form.

**Expected impact:** B+ → A- lift for ecosystem-specificity drafts where the mechanism is
correct but the close is soft. Jun 15 retroactive confirms: the gap is consistent across 5 A-
drafts from 4 signal types (precipitation_extreme, monthly_low, coral, fire-suppression).
The one A in the batch (Nauru) uses the declarative form directly.

**Status:** Drafted. Awaiting human implementation. Highest-leverage *unimplemented* active
proposal in this plan now that P_tier/P_dust/P9 have all closed their tracking: 26 cycles of
evidence, 63+ drafts, same gap to A across every signal type it's been
observed in (precipitation_extreme, monthly_low, coral, fire, all_time_high, monthly_high,
air_quality_hazard, dust_event, regional_sst_anomaly, marine_heatwave, regional_anomaly,
absolute_extreme, fire_footprint, cyclone_rapid_intensification, record, cyclone_landfall,
cyclone_land_threat, hot10 — 18 confirmed types). The
permafrost-carbon fire mechanic (5 instances, all B+/A-), the buffer-failure mechanic
(Galapagos, Congo fire, Stevensville, Basrah, all A-/A-range), and the named-absence
continental-interior form (Basrah ×2, Powderville, all A-/B-range) are the clearest
existence-proofs in the corpus that a declarative-consequence close reliably lifts a draft
once the mechanism is already sound.

### ~~P_dust~~ — Dust_event drafts lack calibrating comparison anchor — **SHIPPED 2026-07-07 (PR #386), CONFIRMED 2026-07-10 (2 independent clean cycles)**

**Observed:** 2026-06-13 — Riyadh, Saudi Arabia dust_event (2,083 μg/m³, score 75)
reached pending with no comparison anchor. 2,083 μg/m³ is ≈ 139× the WHO PM2.5 daily
guideline (15 μg/m³) and ≈ 46× the WHO PM10 guideline (45 μg/m³) — an extraordinary
number that lands flat because the reference is unstated. Draft also includes aerosol
optical depth (0.61) the reader cannot calibrate. Second sentence ends on dispersal
("before heat-driven turbulence disperses it") — resolution of the mechanism, not
consequence. "Model-estimated" qualifier correctly flags source uncertainty; the WHO
multiple is always available as world knowledge regardless.

**Cycles observed:** Jun 13, Jun 17, Jun 25, Jun 28 (4 cycles; Jun 13 = Riyadh 2,083 μg/m³; Jun 17 =
Urumqi 2,260 μg/m³; Jun 25 = Taiz Jun 24 2,271 μg/m³ C+ + Taiz Jun 25 2,135 μg/m³ B- — all 4
corpus drafts through Jun 25 lack WHO calibration anchor; Jun 28 = Taiz [3] 728 μg/m³ C+ — 5th
dust_event corpus draft, no WHO anchor stated [728 ≈ 16× WHO PM10 limit, unstated], mechanism-only
P_close fail, 5th consecutive dust_event with identical opener structure). Jun 15 retroactive confirmed
the reference-frame gap is binding; WHO multiple transforms the grade from B/B- to A-.
**Template convergence confirmed:** all 5 dust_event corpus drafts share identical opener
structure ("[City]: model-estimated dust daily maximum of X µg/m³ on [date] — aerosol optical
depth at Y.") and AOD-only metric. Jun 24's Al Aḥmadī Kuwait (air_quality_hazard) stated the
WHO multiple (10.1×) — confirming the gap is specific to the dust_event signal type, not the
PM signal path generally.
**Last seen:** Jun 28. Taiz [3] C+ ("model-estimated dust daily maximum of 728 μg/m³ on June 27 —
aerosol optical depth at 0.77. Taiz sits at the southwest corner of the Arabian Peninsula where the
summer monsoon low pulls Red Sea and Arabian dust inland through the Tihama coastal plain" —
mechanism-only close, no WHO anchor, 728 ≈ 16× WHO PM10 limit unstated). Urumqi "traps it"
close remains the best dust_event close form; ceiling B- only because the WHO anchor is absent.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
dust_event / air_quality framing section:

> For `dust_event` or `air_quality` signals, the WHO PM2.5 daily guideline (15 μg/m³) is
> always available as world knowledge — it requires no archive data. State the multiple.
> "Riyadh: 2,083 μg/m³ on June 13 — 139× the WHO daily limit" is the natural form. Do NOT
> include aerosol optical depth as a standalone metric unless you state what it means to a
> lay reader (>0.4 = hazy-to-hazardous; >1.0 = extreme). The second sentence should land
> a consequence, not describe dispersal — describing how dust clears is anti-climactic.
> Note: if the signal is model-estimated and no historical comparison is available, the WHO
> multiple IS the comparison. Use it.

**Expected impact:** Transforms dust_event drafts from opaque-number reports into
calibrated-violation framing. The WHO multiple is derivable from any bundle value — no
archive needed. One paragraph addition; no architectural change. Also applies to air_quality
(PM2.5/dust) signal type from the @extremetemps coverage lane. Verify whether
`writer_prompt.py` already has an air_quality framing section before adding a new paragraph.

Jun 30: Phalodi, India dust_event C+ + Taiz, Yemen dust_event C+ — both lack WHO anchor; both use identical opener structure. 6th and 7th consecutive dust_event corpus drafts without the calibrating comparison. No named humor mechanics deployed in either draft (P5 gap confirmed). Template convergence: all 7 dust_event corpus drafts share the opener structure. Phalodi: model-estimated PM2.5, aerosol optical depth stated without calibration. Taiz: same pattern, 3rd Taiz draft in corpus.
Jul 1: Wadi Halfa, Sudan dust_event [14] C+ — 8th consecutive corpus draft without WHO anchor, same opener template. Best-constructed mechanism yet (two-step: haboob winds lift Nubian Desert sediment, Lake Nasser moisture then dampens/settles it) — confirms the gap isn't a writer capability problem, it's an unprompted omission: the writer can build a sophisticated causal chain but still doesn't reach for a reader-facing calibration number. Template convergence now total: 8 of 8 dust_event corpus drafts share the identical opener.
Jul 4: Urumqi, China dust_event [10] B (2,454 μg/m³ ≈ 163× the WHO PM2.5 daily guideline, ≈ 55×
the PM10 guideline, both unstated). "Topographic containment does the rest" is functionally the
same resolution-form close as Jun 17's Urumqi "traps it" — same station, same gap, still no
calibration number. No dust_event drafts appeared Jul 2/Jul 3, so this is the first re-test since
Jul 1; the gap reproduces immediately.
Jul 5: Phalodi, India dust_event [12] C+ (524 μg/m³ ≈ 11.6× the WHO PM10 daily guideline,
unstated). Urumqi, China dust_event [13] B- — **3rd corpus instance of this exact station**
(after Jun 17 and Jul 4), 1,766 μg/m³ ≈ 39× WHO PM10, unstated. Both continue the identical
opener template and resolution-form close. Meanwhile Johannesburg air_quality_hazard [11]
(same cycle) states its WHO multiple (10.9×) unprompted — 2nd consecutive air_quality_hazard
corpus draft to do so (after Jun 24's Al Aḥmadī, 10.1×), while dust_event is now 11 for 11
without it. The split between these two adjacent PM-signal types is the cleanest evidence in
the corpus that the gap is specific to `dust_event`'s bundle construction, not a categorical
"the writer doesn't reach for WHO multiples" problem — it demonstrably does, for a sibling
signal type, unprompted.
**Last seen:** Jul 5 (9 cycles: Jun 13/17/25/28/30 ×2/Jul 1/Jul 4/Jul 5; template convergence
11 of 11).

**Resolution (2026-07-07, PR #386):** Dust bundles now carry a pre-computed
`who_pm10_multiple` field (co-measured PM10 24h mean vs. the WHO 2021 PM10 24h AQG) —
`src/data/air_quality.py` + `src/two_bot/intern/air_quality.py` compute it as a
conditional fact; `writer_prompt.py`'s PM2.5/dust conventions section instructs the
writer to cite it verbatim ("during the event, PM10 averaged 20× the WHO 24-hour
guideline") whenever the bundle has it, and to write the dust tweet without a WHO claim
when it doesn't. This ships the exact fix this proposal specified (state the multiple;
don't fabricate one when the data isn't there) — using the co-measured PM10 anchor
already flowing through the bundle rather than a re-derived PM2.5 comparison, a cleaner
data path than the original proposal text assumed.

**Jul 8 — first empirical confirmation.** Riyadh, Saudi Arabia `dust_event` ("model-estimated
PM10 averaged 27.9× the WHO 24-hour guideline on July 8 — 1,257 μg/m³ against a standard of
45") is the first post-fix `dust_event` draft to reach pending, and it states the multiple
verbatim, WHO-first, exactly as PR #386 prescribes — closing the 11-for-11 gap this plan
tracked for 9 cycles. The old AOD-only opener template is also gone entirely (no aerosol
optical depth mentioned). P_close's separate mechanism-only gap remains open on the same
draft — confirms the two proposals are orthogonal, as expected (P_dust was a MISSING
reader-facing reference; P_close is a different axis entirely).

Jul 9: no `dust_event` draft this cycle — not retested. Still 1 confirmation cycle;
awaiting a 2nd independent clean instance before moving to Resolved.

**Jul 10 — 2nd independent confirmation, CONFIRMED, tracking closed.** Riyadh, Saudi
Arabia `dust_event` ("model-estimated PM10 averaged 1,120 μg/m³ on July 9 — 24.9× the WHO
24-hour guideline") states the multiple verbatim, WHO-first, same prescribed form as Jul
8's confirmation (27.9×) — same city, different reading, 2 days apart with a Jul 9 gap
where no `dust_event` draft appeared. This meets the same 2-independent-clean-cycles bar
P9 closed on Jul 9.

**Status:** SHIPPED in PR #386 (`208159a`), merged 2026-07-07T05:06:48Z, **CONFIRMED
2026-07-10 (2 independent clean cycles: Jul 8, Jul 10).** **9 cycles of evidence before the
fix** (Jun 13/17/25/28/30 ×2/Jul 1/Jul 4/Jul 5; template convergence 11 of 11 `dust_event`
drafts, zero with a WHO anchor). The `air_quality_hazard` sibling type's streak of stating
its own WHO multiple unprompted (Al Aḥmadī, Johannesburg, Soweto, Riyadh Jul 7, Riyadh Jul
8 — 5 cycles) was the existence-proof that made the fix low-risk. Tracking closed, per the
same convention P9 used (entry stays in place with an updated status heading rather than
relocating to Resolved). Reopen if a future `dust_event` draft reverts to the pre-fix
AOD-only opener with no WHO anchor.

### ~~P_tier~~ — Internal scoring-tier / threshold name leaks verbatim into copy (promoted from A3) — **SHIPPED 2026-07-07 (PR #386), CONFIRMED 2026-07-14 (2 independent clean cycles: Ahvaz Jul 10, Basrah Jul 14)**

**Observed:** 2026-06-23 — Mediterranean SST regional_sst_anomaly draft states "exceeds the 2.5°C
tier threshold in NOAA CRW's basin-wide anomaly index" with no explanation of what the tier
means (filed as **A3**, awaiting-evidence, with an explicit "promote if 2+ cycles observed"
condition). 2026-07-01 clears that bar in a single cycle: 3 fresh drafts across 2 signal types
plus 1 carry-over across a 3rd signal type all name their own classification bucket verbatim
instead of describing the world:
- Mediterranean SST (carry-over, graded Jun 28): "just past the 3.5°C tier threshold in the NOAA
  Coral Reef Watch basin average."
- Basrah, Iraq `absolute_extreme` [11]: "above the 47°C absolute-extreme threshold for the
  Northern Subtropical band."
- Al Baṣrah al Qadīmah, Iraq `absolute_extreme` [13]: "at the absolute extreme threshold for the
  Northern Subtropics" — near-verbatim repeat of [11]'s phrasing, 3 days later, same metro area.
- Morrill Fire, Nebraska `fire_footprint` [12]: "past the 250,000-hectare tier that marks a
  continent-scale footprint."

All four are otherwise structurally sound drafts — real signal, correct ecosystem mechanism, two
with genuinely strong closes (Morrill Fire's dune-destabilization consequence, Basrah's named-
absence close) — but the tier-naming reads as the bot quoting its own internal scoring rubric
rather than speaking in its voice. This is a Wodehouse violation of a kind not previously named
in this doc: not approximation, not restate-padding, not a poetry attempt, but **citing your own
methodology** — the prose equivalent of a comedian explaining the joke's premise before telling
it. `absolute_extreme` and `fire_footprint` are both first-appearance signal types in the corpus,
so this may be a structural feature of how their bundles are built (the tier/threshold label is
probably a literal field the writer is echoing) rather than a one-off phrasing choice.

**Cycles observed:** Jun 23 (A3 origin, 1 instance), Jul 1 (3 fresh instances across 2 new signal
types, 1 carry-over instance in a 3rd type), Jul 2 (1 more instance, same phrase family, same
signal type), Jul 3 (1 more instance, 4th signal type). **5 cycles / 7 instances / 4 signal
types** once A3's Jun 23 and Jun 28's (unflagged-at-the-time) Mediterranean instance are counted
alongside Jul 1–3.

Jul 2: Basrah, Iraq `absolute_extreme` [16]: "above the 47°C threshold marking absolute extremes
for this latitude band" — a third near-verbatim repeat of the [11]/[13] phrase family, this time
on a 48°C reading (the highest of the three Basra-area drafts). All three Basra-area drafts now
share both the tier-jargon leak and a duplicate-location concern (see `docs/DRAFT_CORPUS.md` Jul 2
patterns). The proposal's core claim — that `absolute_extreme` structurally echoes an internal
tier/threshold field — is now supported by 3 of 3 corpus drafts of that signal type.
Jul 3: Typhoon Bavi `cyclone_rapid_intensification` [20]: "the rapid-intensification threshold is
30 kt in 24 hours" — a **4th signal type**, and the first outside the
record/threshold-style family (`regional_sst_anomaly`, `absolute_extreme`, `fire_footprint`
were all "how far past a static line" signals; `cyclone_rapid_intensification` is a
rate-of-change signal, and it still exhibits the exact same tier-citation shape). This is the
first `cyclone_rapid_intensification` draft in the corpus, so — like `absolute_extreme` and
`fire_footprint` on their debuts — the violation appears on the very first instance, reinforcing
that this is a structural bundle-field-echo problem, not a drift that accumulates over many
drafts of a type. The proposal's scope is now confirmed broader than "record-adjacent signals" —
any signal type with an internal severity/classification field is at risk.
Jul 4: Two more `absolute_extreme` instances, both repeating the violation — Basrah, Iraq [4]
("the absolute extreme threshold for the Northern Subtropics") and Al Başrah al Qadīmah [6]
("above the 47°C absolute-extreme threshold for the Northern Subtropics"), the 4th and 5th
Basra-area instances overall. Both cap at B even though [6]'s close is a genuine P_close
positive — reconfirms the pattern holds regardless of close quality. **Counter-instance:**
Typhoon Bavi's 2nd corpus draft (`cyclone_rapid_intensification`) does NOT repeat the
violation this time — no internal threshold language at all, just the raw category jump and
wind numbers. First evidence the violation isn't deterministic per signal type/bundle field;
worth watching whether it's `WRITER_SAMPLES=2`/critic-revise occasionally filtering it, pure
model stochasticity, or something else. Does not change the proposal's core claim (9 of 10
corpus instances across these 4 types still show it) but is worth tracking as a data point on
implementation urgency vs. natural variance.
Jul 5: Doha, Qatar `absolute_extreme` [15]: "the absolute extreme threshold for the northern
subtropical band" — the same phrase family, but on a **brand-new city with no data-path
relationship to the Basra-area cluster** (Basrah + Al Başrah al Qadīmah, both Iraq; Doha is
~1,500 km away in Qatar). This is the single strongest data point yet that the violation is
tied to the `absolute_extreme` bundle's internal tier field itself, not to one location's
ingestion or a regional quirk. Doha's close is also the best `absolute_extreme` P_close
instance in the corpus ("closing off the evaporative cooling that makes extreme dry heat
survivable") and it still caps at B — reconfirms P_tier overrides close quality entirely,
unlike P_close or P_compound which are soft caps.
**Last seen:** Jul 5 (7 cycles / 10 instances / 4 signal types; 1st cross-location
confirmation within `absolute_extreme`; 1 clean counter-instance remains, from Jul 4's
Typhoon Bavi).
Jul 7 (final pre-fix evidence — both generated ~1.5h before PR #386 merged): Zaragoza,
Spain `absolute_extreme` [1]: "the absolute-extreme threshold for northern mid-latitudes" —
**a new band name** ("northern mid-latitudes," distinct from every prior instance's
"Northern Subtropics"/"Northern Subtropical band"), confirming the citation habit
reproduces across whatever internal band the bundle carries, not one hardcoded string.
Ahvaz, Iran `absolute_extreme` [2]: "above the 47°C absolute-extreme threshold for the
Northern Subtropics" — same phrase family as Basrah/Al Başrah, expanding the cluster to a
2nd country (Iran) though still the same regional climate zone, not an independent
cross-location confirmation like Doha's. **8th cycle / 12 instances / still 4 signal
types.**
**Last seen:** Jul 7 (8 cycles / 12 instances / 4 signal types).
Jul 8: no draft of any of the 4 originally-tracked target types (`absolute_extreme`,
`fire_footprint`, `cyclone_rapid_intensification`, `regional_sst_anomaly`) — the fix
remains formally unconfirmed on the exact types this proposal was filed against.
Indirect supporting evidence: the corpus's 2 brand-new cyclone signal kinds
(`cyclone_landfall`, `cyclone_land_threat`, both debuting today) are governed by the
same "DETECTION PLUMBING IS NOT A FACT" rule PR #386 shipped (the rule covers the whole
cyclone bundle family, not just `cyclone_rapid_intensification`), and both came back
clean of tier-jargon. This is consistent with the fix working but is not the same as a
confirmation on a named target type — do not move to Resolved on this basis alone.
**Last seen (violation):** Jul 7. **Not yet tested on a named target type.**
Jul 9: no draft of any of the 4 target types, nor of the 2 cyclone kinds that gave
indirect supporting evidence Jul 8 (all_time_high and precipitation_extreme only). Still
formally unconfirmed.

**Jul 10 — 1st post-fix confirmation on a named target type.** Ahvaz, Iran
`absolute_extreme` ("just above the 47°C threshold where heat in this part of the Middle
East historically crosses into the range where shade and rest alone stop being enough")
is the first post-fix draft of any of the 4 originally-tracked target types to reach
pending (3+ days after the 05:06 UTC merge). No band-label citation ("Northern
Subtropics"/"Northern Subtropical band"/"northern mid-latitudes" — every prior instance's
form), no "absolute-extreme threshold" phrase. The word "threshold" survives but is
attached to the raw observed number (47°C, explicitly citable per the shipped rule) and a
physiological consequence, not a classification bucket — the exact distinction the
resolution draws. Direct same-city comparison is available: this same Ahvaz station's Jul
7 pre-fix draft used "above the 47°C absolute-extreme threshold for the Northern
Subtropics"; this draft, post-fix, does not. Graded A- (see `docs/DRAFT_CORPUS.md` Jul 10
entry) — the corpus's first A-grade `absolute_extreme` draft, now that P_tier no longer
caps it. **This is 1 confirmation cycle, the same position P_dust was in after Jul 8** —
watch for a 2nd post-fix instance on any of the 4 target types before moving to Resolved.
**Last seen (pre-Jul-14):** Jul 10 (1 post-fix confirmation; 8 cycles / 12 instances / 4
signal types of pre-fix evidence unchanged).

**Jul 14 — 2nd independent confirmation, CONFIRMED, tracking closed.** Basrah, Iraq
`absolute_extreme` ("3°C above the 47°C threshold where the body's cooling mechanisms begin
to fail faster than they can recover") is the 2nd post-fix draft of any of the 4
originally-tracked target types to reach pending, and it repeats Ahvaz's clean form exactly:
the raw 47°C number stated plainly, explained via a physiological consequence a reader can
verify, no "Northern Subtropics"/"Northern Subtropical band"/band-name citation at all —
notably on the same general Basra-area/Iraq-Iran Gulf cluster that produced 5+ pre-fix
violations (Basrah ×3, Al Başrah al Qadīmah ×2) between Jul 1 and Jul 5. Direct within-
cluster comparison: this exact city's own pre-fix corpus history used "above the 47°C
absolute-extreme threshold for the Northern Subtropical band" (Jul 1) and "above the 47°C
threshold marking absolute extremes for this latitude band" (Jul 2); this draft, 12 days
later and post-fix, does neither. Paired with a declarative P_close ("removes the ceiling"),
graded A- — the corpus's 2nd A-grade `absolute_extreme` draft, both post-fix (Ahvaz Jul 10,
Basrah Jul 14). This meets the same 2-independent-clean-cycles bar P_dust and P9 closed on.
**Last seen:** Jul 14 (2 post-fix confirmations: Ahvaz Jul 10, Basrah Jul 14; 8 cycles / 12
instances / 4 signal types of pre-fix evidence unchanged).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`,
near the existing HARD RULES / bad-examples list:

> Never name your own scoring machinery. If the bundle carries an internal category label like
> "tier," "threshold," "band," or a named severity class ("continent-scale," "absolute-extreme"),
> state the raw number and let it stand — do NOT quote the label back to the reader. "Basrah is
> forecast to hit 47.2°C (117°F)" is voice. "Above the 47°C absolute-extreme threshold for the
> Northern Subtropical band" is the bot reading its own rubric out loud. Bad: "past the
> 250,000-hectare tier that marks a continent-scale footprint." Good: "has burned 259,820
> hectares since March 13" — the number alone, at this scale, needs no label. Test: if the
> phrase names a bucket rather than a place, time, or physical quantity, cut it.

**Expected impact:** Unlocks two brand-new signal types (`absolute_extreme`, `fire_footprint`)
from a B ceiling toward A-/B+ — both current instances have strong closes and would clear the
cap immediately once sentence 1 stops citing methodology. Also fixes the still-open Mediterranean
SST regression from A3. One paragraph addition; complements (does not duplicate) the P_dust fix,
which addresses a related but distinct gap (dust_event's problem is a MISSING reader-facing
reference; P_tier's problem is an UNWANTED internal-only reference already present).

**Resolution (2026-07-07, PR #386):** `writer_prompt.py` gained a "DETECTION PLUMBING IS
NOT A FACT" rule naming exactly this failure mode: latitude-band names (`band_label`),
per-class editorial score thresholds, and detector trigger definitions are the bot's own
detection configuration, not something a reader can verify — never cite them. What stays
citable: observed actuals (real deltas like "winds climbing 40 kt in 24 hours") and
bundle-designed reader anchors (`frp_tier` phrasings, Saffir-Simpson, DHW levels,
Beaufort, WHO multiples). Explicit test provided: "is this a fact about the WORLD a
reader could look up, or a fact about this bot's configuration? World: cite. Bot:
never." Paired with a fact-check rule (m) and a critic `internal_taxonomy_leak` kill in
the same PR — the E1 dual-gate discipline this plan's other shipped fixes have used.

**Status:** SHIPPED in PR #386 (`208159a`), merged 2026-07-07T05:06:48Z, **CONFIRMED
2026-07-14 (2 independent clean cycles: Jul 10, Jul 14).** **8 cycles / 12 instances / 4
signal types of pre-fix evidence**, including confirmation outside the Basra-area cluster
(Doha) and across multiple internal band names (Zaragoza's "northern mid-latitudes" vs. the
Basra cluster's "Northern Subtropics") — and, notably, the 2nd post-fix confirmation landed
on the exact Basra-area cluster that generated the most pre-fix evidence, the strongest
within-location before/after comparison available in this plan. Tracking closed, per the
same convention P_dust and P9 used (entry stays in place with an updated status heading
rather than relocating to Resolved). Reopen if a future `absolute_extreme`/`fire_footprint`/
`cyclone_rapid_intensification`/`regional_sst_anomaly` draft reverts to citing its own
band/tier/threshold label verbatim.
Also watch for the closely-related "signal"/self-naming variant filed as new proposal A4
below — a post-fix `air_quality_hazard` draft this cycle shows a lexically different but
conceptually adjacent self-reference the shipped rule's wording may not explicitly cover.

### ~~P9~~ — precipitation_extreme opener template convergence + restate-math — **SHIPPED 2026-07-07 (PR #397), CONFIRMED 2026-07-09 (2 independent clean cycles)**

**Observed:** First observed 2026-06-18. Archived 2026-07-03 after 3 consecutive fresh-draft
cycles without a `precipitation_extreme` draft (Jul 1, Jul 2, Jul 3), with an explicit note
that the archival was absence-of-opportunity, not a confirmed fix, and that the pattern was
"very likely to recur on the very next instance." **Reopened 2026-07-04**, on that very next
instance: both fresh `precipitation_extreme` drafts this cycle repeat the pattern. Barrow,
Alaska: "Barrow, Alaska recorded 498.8 mm of rain in 7 days — 198.8 mm above the previous 7-day
record of 300.0 mm" (opener template + restate-math: 198.8 is arithmetic from the two other
values already stated). Astana, Kazakhstan: "Astana, Kazakhstan received 358.1 mm of rain in
seven days ending July 2 — 58.1 mm above the previous 7-day record of 300.0 mm" (same
construction, same restate-math shape). Astana additionally strands the batch's strongest
available punchline: its own third sentence states the region's annual rainfall average as
"roughly 300 mm total" — the 7-day total exceeds a typical year's rainfall — without ever
connecting the two numbers for the reader.

**Cycles observed (pre-fix):** 10 cycles total (Jun 7, Jun 18, Jun 22 retroactive, Jun 25,
Jun 26 ×3, Jun 28, Jun 29, Jun 30, reopened Jul 4). Confirmed pattern stood at 15 of 15 corpus
`precipitation_extreme` drafts sharing the opener structure. Not tested Jul 5 or Jul 7 (no
`precipitation_extreme` draft in either cycle — 2 consecutive precip-free fresh-draft cycles,
one short of the 3-cycle re-archive threshold when the fix shipped).
**Last seen (pre-fix):** Jul 4.

**Resolution (2026-07-07 evening, PR #397):** `writer_prompt.py`'s precipitation section
gained a "four moves" framing (Section: Precipitation bundles) that bans re-deriving the
margin as arithmetic ("never re-derive a per-day rate... derived rates are BUNDLE_FACT
mismatches waiting to happen and read as effort"), explicitly reclassifies
`alert_threshold_mm` as internal detection config never to be cited as a record or scale,
and prescribes the annual/seasonal-baseline ratio ("a week's rain where a year's usually
falls") as the significance anchor for bare-threshold bundles — this ships almost exactly
the fix this proposal specified, including the baseline-comparison-as-closer move.

**Jul 8 — first empirical confirmation, and the strongest possible test:** all 3 fresh
`precipitation_extreme` drafts this cycle are clean. Barrow, Alaska ("one storm just
delivered two-thirds of a normal year in a day"): no restate-math, declarative annual-ratio
close. Astana, Kazakhstan ("this single storm delivered roughly a sixth of a typical year's
rain"): same clean form, colon/"smashing"-lead opener instead of the old template. Anchorage,
Alaska ("roughly a full year's average in one week... compressing what would otherwise be
weeks of accumulation into days"): ratio-anchor leads sentence 1 instead of being stranded as
a closer, correctly omits record language on a bare `multi_day_accumulation` bundle. This is
the first `precipitation_extreme` batch in the corpus's history with zero P9 violations across
all 3 fresh drafts — closing a pattern that held at 15-for-15 for 10 cycles.
**Last seen (violation):** Jul 4. **First clean cycle:** Jul 8.

**Proposed fix (as shipped, for reference):** burn the default opener (period-and-restate,
lead-with-mechanism, colon-lead, ratio-as-lead forms all now observed in the corpus); ban
restate-math; state the annual/seasonal baseline ratio directly as significance when the
bundle supports it. Full worked examples preserved in `docs/DRAFT_CORPUS.md`'s Jun
7/18/22/25/26/28/29/30/Jul 4/Jul 8 entries.

**Jul 9 — 2nd empirical confirmation.** Anchorage, Alaska `precipitation_extreme` (61.2
mm/day against a 0.9 mm prior daily record): no restate-math, no legacy opener template —
"against a previous daily record of 0.9 mm set earlier in 2026" is a distinct, clean
construction. This confirms the fix holds on its narrow terms a 2nd time on an
independent draft. **Caveat worth tracking, not re-opening the proposal over:** the draft
leaves a real punchline unstated — 61.2 mm against 0.9 mm is exactly 68×, the most
dramatic ratio in the `precipitation_extreme` corpus, and unlike Jul 4's Astana (which
needed an external annual baseline), this ratio is arithmetic on the two numbers already
in the sentence. PR #397's shipped rule prescribes the annual/seasonal-baseline ratio
specifically, not a record-to-record ratio, so this isn't a rule violation — but it's the
same shape of missed opportunity, on a bundle shape (single-day record vs. prior record)
distinct from the one the fix was proven against (7-day accumulation with an annual
baseline, all 3 of Jul 8's drafts). Watch whether daily-record precipitation_extreme
bundles keep reverting to a flatter close than accumulation bundles; if a 2nd instance of
this specific gap appears, it may warrant a small follow-on proposal scoped to
record-to-record ratios specifically.

**Status:** SHIPPED in PR #397, merged 2026-07-07 (evening session, after that day's 15:00
UTC grading run — this plan's Jul 7 entry still showed it as unimplemented for that reason).
**CONFIRMED — 2 independent clean cycles** (Jul 8, 3/3 clean; Jul 9, 1/1 clean). Tracking
closes here; reopen only if restate-math or the pre-fix opener template reappears in a
future `precipitation_extreme` draft.

~~### P_new — Cold-record quality floor~~ → **[Archived 2026-06-21 — see Resolved section]**

### P5 — Name humor moves as available tools in writer_prompt.py

**Observed:** Apr 25-27 corpus — SYSTEM_PROMPT named only a subset of available moves;
Gemini converged on the most-explicit ones (era anchors). Unnamed mechanics (idiom-flip,
accelerating-warming, ecosystem specificity) appeared inconsistently. In the two-bot
context, the Sonnet writer also defaults to the most-stated patterns unless the full
palette is named.

**Cycles observed:** Apr 25, Apr 27, May 13, May 19 (4 cycles; era anchor over-deployment
+ mechanic convergence in v2 era; no named mechanics in fire drafts in two-bot era).
**Last seen:** Jun 28 (weak: steppe ecosystem-incongruity in Astana [5] deployed organically —
third-sentence "Astana sits in the driest interior of the Eurasian steppe" is a named
ecosystem-specificity move used without explicit prompting. Taiz dust_event [3] and Casper [7]
showed no named humor moves beyond mechanism. Same pattern as Jun 25/26/27: geographic categories
self-select their mechanics naturally; dust_event and monthly_low do not.
Prior Jun 26 note: Anchorage B chose orographic-stall mechanism as system clause organically;
Aktobe C+ deployed half-year aridity ratio as close naturally. All 3 precipitation_extreme;
all 3 used system-clause specificity without prompting. No named humor move beyond mechanism/ratio.
Prior Jun 25 note: Siberia fire B+ deployed peatland carbon + companion-fire peer comparison;
Barrow B+ used annual-precipitation ratio. Michigan monthly_low B and Taiz dust_event ×2 showed
no named humor moves. Same pattern across cycles: fire/precip categories self-select mechanics;
dust_event/monthly_low categories do not.
Jun 29: Full mechanic variety across 5 fresh drafts — floor/ceiling inversion (marine_heatwave),
ecosystem incongruity (Congo fire), latitude peer-comparison (Prudhoe Bay), declarative ecosystem
specificity (Amsterdam). Not one draft needed explicit P5 prompting; mechanics deployed organically.
3rd consecutive graded cycle where all deployed mechanics appeared without explicit naming.
Jun 30: 2 dust_event drafts (Phalodi + Taiz) graded C+ — both deploy zero named humor mechanics. Mechanism-only second sentences, no period-and-restate, no idiom-flip, no comic triple. 2nd consecutive dust_event cycle without a named mechanic across all corpus drafts in this category. Precipitation drafts (Astana/Antwerpen/Colorado) also show no named moves beyond mechanism-as-system-clause. Pattern confirmed: dust_event is the current gap category for P5; precipitation_extreme continues self-selecting mechanism without named humor moves.
Negative evidence accumulating: 5 consecutive fresh-draft cycles (Jun 7 / Jun 25-26 / Jun 27 / Jun 29 / Jun 30) show precipitation/fire named mechanics deploying naturally. P5 urgency split: fire/precip/record — organically deploying, low urgency; dust_event/monthly_low — confirmed gap, higher urgency.
Jul 1: Mixed. Basrah [11] and Morrill Fire [12] both deploy real named-absence / causal-chain
mechanics organically (no explicit prompting needed) — consistent with the "extreme-heat and
fire-adjacent categories self-select" pattern. Wadi Halfa [14] dust_event again shows zero named
humor mechanic despite a genuinely sophisticated two-step physical chain — 3rd consecutive
dust_event cycle confirming the gap is category-specific, not writer-capability-limited (the
writer clearly CAN build layered mechanisms; it just doesn't reach for a landing move in this
category). Al Baṣrah al Qadīmah [13] similarly no named mechanic beyond mechanism description.
Jul 3: Canadian Arctic fire [18]/[19] both deploy the carbon-release mechanic organically (no
explicit prompting) — 3rd fire draft pair confirming fire self-selects mechanics naturally.
Typhoon Bavi [20], the corpus's first `cyclone_rapid_intensification` draft, shows the ratio move
("crossed it by nearly double") but built on top of a P_tier violation rather than a clean named
mechanic — inconclusive as P5 evidence either way (the move is present, but not cleanly, so it's
not a strong data point for "categories with a threshold field self-select cleanly").
**Last seen:** Jul 3 (fire self-selecting for a 3rd consecutive fire cycle; dust_event still the
confirmed gap category as of its last appearance Jul 1; no dust_event drafts this cycle to retest).
Jul 4: Mixed, consistent with the established split. Extreme-heat/absolute_extreme self-select
mechanics organically again (Loxahatchee's convection-stall contrast, Basrah/Al Başrah's
named-absence forms). Urumqi dust_event again shows no named mechanic beyond mechanism
description — 4th consecutive dust_event cycle confirming the gap. Typhoon Bavi's 2nd draft
deploys a clean stakes-consequence move without explicit prompting (see P_close) — another data
point that categories with strong physical stakes self-select even on their 2nd corpus instance.
**Last seen:** Jul 4 (dust_event gap now 4 consecutive confirming cycles: Jun 30, Jul 1, and no
dust_event Jul 2/Jul 3, then Jul 4).
Jul 5: Urumqi dust_event (3rd corpus instance of this station) again shows zero named humor
mechanic beyond mechanism/topography description — 5th cycle confirming the dust_event gap.
Phalodi dust_event, same cycle, also zero named mechanic. Meanwhile eastern Siberia fire
self-selects the permafrost-carbon mechanic cleanly (4th consecutive fire cycle confirming
organic self-selection, no explicit prompting) and Johannesburg air_quality_hazard again
builds a real causal chain unprompted (named season + source attribution — 2nd consecutive
air_quality_hazard cycle confirming this type self-selects like fire/absolute_extreme, unlike
its dust_event sibling). The fire/absolute_extreme/air_quality_hazard vs. dust_event split
continues to sharpen with each cycle.
**Last seen:** Jul 5 (dust_event gap now 5 consecutive confirming cycles: Jun 30, Jul 1, Jul 4,
Jul 5, plus Jun 28; fire self-selection streak now 4 cycles; air_quality_hazard self-selection
streak now 2 cycles).
Jul 7: No dust_event draft this cycle — that gap's count holds at 5 cycles, unchanged.
`air_quality_hazard` self-selects for a 4th instance across a 3rd distinct cycle: Soweto
("coal season" + household-fuel source attribution + "nowhere to vent") and Riyadh (WHO
ratio + heat-suppresses-mixing mechanism) both build real causal chains unprompted, extending
the Jun 24/Jul 5/Jul 7 streak. **New signal type `record` debuts with zero named humor move**
(Aibonito states only expository rarity-context, no comic/incongruity/declarative device) —
too early to call this a confirmed gap category on 1 instance, but worth watching alongside
dust_event given both are debuting into the same "explains but doesn't land" shape.
**Last seen:** Jul 7 (dust_event gap unchanged at 5 cycles; air_quality_hazard
self-selection now 4 instances/3 cycles; `record` new-type instance inconclusive, 1 data
point).
Jul 8: dust_event gap continues — Riyadh's `dust_event` draft builds a genuine two-source
causal chain (Nafud + Rub' al Khali deserts feeding one column under peak shamal winds)
but, per the established convention for this category, sophisticated mechanism
construction still isn't counted as a named humor move — 6th cycle confirming the gap
(Jun 28, Jun 30, Jul 1, Jul 4, Jul 5, now Jul 8; Jul 7 had no dust_event draft to test).
Meanwhile
`air_quality_hazard` self-selects for a 5th cycle (Riyadh's other draft, same day: WHO
ratio + convective-mixing mechanism), and its close surfaces a genuinely new move —
"this is a basin-scale loading, not a street-corner spike," a declarative
**scale-honesty contrast** not on the existing 8-item list. 1 instance; watching for a
2nd before proposing its formal addition to the "Voice moves available" list below.
**Last seen:** Jul 8 (dust_event gap now 6 cycles; air_quality_hazard self-selection now
5 instances/4 cycles; candidate 9th move — scale-honesty contrast — 1 instance).
Jul 9: split evidence. Stevensville, Maryland `all_time_high` self-selects the
buffer-failure mechanic cleanly and unprompted — consistent with the extreme-heat/record
family's established organic-deployment pattern. Anchorage, Alaska
`precipitation_extreme`, though, shows the category can regress: this same city's Jul 8
draft (a 7-day accumulation bundle) self-selected a strong declarative ratio-anchor move,
but today's daily-record-bundle draft falls back to mechanism-only description with no
named move at all — the same station, 2 days apart, opposite outcomes. Precipitation's
self-selection appears to depend on bundle shape (accumulation bundles land moves;
single-day-record bundles default to mechanism-only), not just signal category.
**Last seen:** Jul 9 (extreme-heat/record family self-selection streak continues;
precipitation_extreme now shows metric-dependent split behavior rather than uniform
self-selection).
Jul 10: dust_event gap continues — Riyadh again builds real named mechanism (Shamal wind
system, two named source deserts) but, per the established convention, this still isn't
counted as a landed move — 7th cycle confirming the gap (Jun 28, Jun 30, Jul 1, Jul 4, Jul
5, Jul 8, now Jul 10; Jul 7/9 had no dust_event draft to test). Ahvaz, Iran
`absolute_extreme` self-selects a clean declarative survivability-consequence move
unprompted, extending the extreme-heat/record family's streak. Tepee Creek, Montana
`all_time_high` shows only an implied close (states the norm, doesn't declare it broke) —
weaker self-selection than Stevensville's Jul 9 buffer-failure form or Ahvaz's today,
consistent with the pattern that `all_time_high` self-selects a real move less
consistently than `absolute_extreme`/`fire`/`air_quality_hazard`.
**Last seen:** Jul 10 (dust_event gap now 7 cycles; extreme-heat self-selection streak
continues via Ahvaz; all_time_high remains the more inconsistent record-family member).
Jul 11: fire self-selects the permafrost-carbon mechanic again on both fresh drafts
(interior Alaska, western Siberia) — 5th/6th consecutive confirming fire cycle. New wrinkle:
both instances reuse a prior corpus draft's exact phrasing rather than composing a fresh
move, which is a different failure mode than P5 tracks (P5 is about whether ANY named
mechanic is used, not phrase-level uniqueness) — filed separately as new proposal A6 below,
not folded into this proposal's count.
**Last seen (pre-Jul-14):** Jul 11 (fire self-selection streak now 5/6 cycles, unchanged
qualitatively; dust_event gap not tested this cycle — no dust_event draft).
Jul 14: **fire's self-selection streak breaks for the first time.** Ontario, Canada's
3-signal fire cluster (2,374.8/883.7/817.1 MW) closes with a bare restatement of the count
("Three simultaneous signals above 800 MW in one Canadian afternoon") — no forest type, no
permafrost/peat framing, no ecosystem specificity, nothing beyond the numbers already given.
The writer's own stated reasoning for this draft names the cause directly: "the cluster
enumeration is the system clause, requiring no invented context and no archive" — i.e. the
multi-fire-cluster framing was treated as sufficient on its own, in place of reaching for a
mechanic. This is a genuine counter-instance, not a data gap: this SAME cycle's western
Siberia carry-over (also a 3-signal cluster, graded Jul 11) proves the cluster format and a
named mechanic ("burning across peat that took centuries to accumulate") are compatible —
so the gap tracks with the *specific angle chosen* (bare enumeration vs.
enumeration-plus-mechanism), not with clusters as a class. Basrah's `absolute_extreme`
self-selects a clean declarative mechanic unprompted, extending the extreme-heat family's
streak; Randolph's `all_time_high` self-selects a real elevation mechanism but only reaches
the implied form (see P_close), consistent with `all_time_high` remaining the more
inconsistent record-family member (per Jul 10's note).
**Last seen (pre-Jul-16):** Jul 14 (fire self-selection streak breaks for the first time via
Ontario's cluster-enumeration-only draft, after 6 consecutive confirming cycles Jun 25 →
Jul 11; dust_event gap not tested this cycle — no dust_event draft).
Jul 16: `all_time_high` self-selects a real named-absence mechanism unprompted (Powderville —
"no marine layer and no terrain to interrupt heat building") — extends the extreme-heat/
record family's organic-deployment pattern. **`hot10` self-selects a real mechanic on its
corpus debut** (Oslo — peer/climate-analogy comparison + declarative accelerating-warming
reframe), joining fire/absolute_extreme/air_quality_hazard/marine_heatwave as another
self-selecting type on first appearance; n=1, watching for a 2nd instance before calling it
a confirmed streak the way fire's was before Jul 14's break. dust_event gap not tested this
cycle (no dust_event draft); fire self-selection not tested (no fresh fire draft, only
carry-overs already counted at Jul 11's grading).
**Last seen (pre-Jul-17):** Jul 16 (`all_time_high` self-selects again; `hot10` self-selects on
debut, n=1; dust_event/fire gaps not retested this cycle).
Jul 17: `absolute_extreme` self-selects clean mechanics on 2 of 3 fresh instances (Bandar-E
Mahshahr's Gulf-humidity framing, Al Basrah's delta-survivability framing — both organic, no
prompting); the 3rd instance (Basrah) technically deploys a mechanic too but strands it outside
the closer (see P_close). `all_time_high` self-selects again (Deaver WY — terrain-traps-heat
mechanism), 3rd consecutive confirming cycle. **`hot10` confirms a 2nd self-selecting instance**
(Tunis — leaderboard-aggregate reframe, a genuinely new move variant, not a repeat of Oslo's
peer-comparison form) — no longer n=1, now a confirmed self-selecting type alongside fire/
absolute_extreme/air_quality_hazard/marine_heatwave. dust_event gap not tested (no dust_event
draft); fire self-selection not tested (no fresh fire draft, only unchanged carry-overs).
**Last seen (pre-Jul-18):** Jul 17 (`absolute_extreme`/`all_time_high` self-select again; `hot10`
confirms 2nd self-selecting instance; dust_event/fire gaps not retested this cycle).
Jul 18: `all_time_high` self-selects a real named-absence mechanism unprompted for a **3rd
consecutive cycle** (Wausaukee — "without the lake bleeding it off first," after Powderville Jul
16 and Deaver Jul 17). `air_quality_hazard` self-selects its strongest device yet (Delhi's
monsoon expectation-reversal, "rains are supposed to wash the air... the seasonal scour isn't
keeping up") — 3rd consecutive corpus `air_quality_hazard` draft to build a real causal/rhetorical
device unprompted (after Al Aḥmadī, Johannesburg). `precipitation_extreme` is mixed: Astana
reaches for a genuinely new move (companion-city triple + annual-baseline contrast, see P_close)
while Anchorage's mechanism has calcified into a 3rd-instance self-repeat (see new active proposal
A7) — worth reading as evidence that this category's organic-deployment streak is real but
starting to show the same per-location formulaic risk P6/P9 addressed at the category level.
`absolute_extreme`/`dust_event`/fire gaps not tested (no fresh instance of any this cycle).
**Last seen:** Jul 18 (`all_time_high` 3rd consecutive self-selecting cycle; `air_quality_hazard`
3rd consecutive self-selecting cycle; `precipitation_extreme` mixed — 1 new move, 1 self-echo).
**Proposed fix (REDIRECTED to two-bot):** Add a "Voice moves available" section to
`src/two_bot/prompts/writer_prompt.py` after the hard rules. List: comic triple
(period-stop), idiom-flip (Steven Wright), understatement closer (British dry),
period-and-restate (Anchorage move), deadpan delivery, accelerating-warming, era anchor,
ecosystem-specific specificity. Conclude: *"None of these are mandatory. When the number
alone is striking, deliver the data plainly. Forced humor breaks the spell."*

**Expected impact:** Richer move palette → more variety across drafts → less convergence
on the easy default. Note: coral drafts in the May 19 cycle produced named-move variants
without explicit prompting (contrast-reveal, expectation-reversal, understatement closer)
— the coral writer prompt may already be doing the work. Verify whether `writer_prompt.py`
has a coral-specific named-moves section before implementing.

**Status:** Drafted. Target updated from dead generator.py SYSTEM_PROMPT to
`src/two_bot/prompts/writer_prompt.py`. Awaiting human implementation. Jun 15 retroactive
extends evidence to fire/hot10/dust categories; coral/record categories may not need it.

~~### P7 — Coral opener formula convergence~~ → **[Resolved 2026-06-15 — see Resolved section]**

~~### P8 — Snow/extreme record: ratio-as-punchline unused~~ → **[Resolved 2026-06-17 — see Resolved section]**

### P_compound — Compound-qualifier first sentence: choose archive OR margin, not both

**Observed:** 2026-06-28 — two record-type drafts in the same cycle open with both archive-depth
qualifier AND margin qualifier in one sentence. Beaver Dams UT all_time_high [6]: "Beaver Dams,
Utah hit 104°F (39.9°C) on June 25 — hottest daily maximum in 23 years of records, 15°F above
the 2020 mark." Casper WY monthly_low [7]: "Casper, Wyoming hit 27°F (-2.8°C) on June 25 —
coldest June low in 26 years of records, 3°F below the 2018 mark." Double-qualification dilutes
both data points: neither archive depth ("23 years of records") nor margin ("15°F above the 2020
mark") lands with full force when immediately followed by the other. The punchline is split, and
neither half is the punchline. Compare: Jun 15 retroactive Cope Rch TX A- ("hottest daily
maximum ever recorded, 1.5°F above the 2018 mark") — same structure, but "ever recorded" is a
stronger qualifier than "in 23 years" and 1.5°F margin is implicit-tight rather than stated-loose.

**Cycles observed:** Jun 28 (1 cycle; 2 of 5 fresh drafts in the same cycle — confirms the
pattern is structural, not coincidence in a single draft); Jun 29 (Prudhoe Bay [5] A-:
"hottest daily maximum in 24 years of records, 2°F above the 2024 mark" — same archive+margin
double-qualifier structure. Smaller margin (2°F) makes double-qualification less visible but
the structural pattern recurs in record-type openers. 2nd consecutive cycle with P_compound.);
Jun 30 (Prudhoe Bay all_time_high carry-over — same double-qualifier structure observed again
in the 3rd grading cycle where this draft appears. Pattern holds across grading cycles:
archive+margin double-qualifier is the default form for record-type openers.)
Jul 2 (Ft Green, Florida all_time_high [15] and [17], near-duplicate drafts one day apart — both
open "hottest daily maximum in 26 years of records, 1°F above the 2025 mark," identical phrasing
in both. A gap of 1 cycle since Jun 30 — the pattern was dormant Jul 1 [that cycle's 4 fresh
drafts were monthly-record-free: 2 `absolute_extreme`, 1 `fire_footprint`, 1 `dust_event`, none of
which use the archive+margin record-opener form] — but recurred immediately once an `all_time_high`
draft reappeared, confirming the gap was signal-mix, not a resolving trend.)
Jul 4 (Island Pond, Vermont [1] and Loxahatchee, Florida [3], both `all_time_high`, both open
"hottest daily maximum in 37 years of records, 1°F above the [year] mark" — identical archive
depth and margin by coincidence, same double-qualifier construction. Notable split: Loxahatchee
overcomes it with a strong P_close-positive close and grades A-; Island Pond doesn't and grades
B+ — reconfirms P_compound softens rather than hard-caps a draft, unlike P_tier.)
**Last seen:** Jul 4 (5 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4). **Not tested Jul 5** — none
of today's 5 fresh drafts were record-type (`all_time_high`/monthly_low/monthly_high); the
2 carry-over `all_time_high` drafts (Island Pond, Loxahatchee) were already counted at Jul 4's
grading. One untested cycle does not meet the 3-consecutive-absence bar for re-archiving.
Jul 7: Snowshoe, West Virginia `all_time_high`: "hottest daily maximum in 52 years of
records, 2°F above the 1986 mark" — same archive+margin double-qualifier construction, 6th
cycle. Overcome by a strong declarative close (elevation-inversion incongruity) and grades
A- anyway — same soften-not-cap pattern as Jul 4's Loxahatchee. Aibonito, Puerto Rico's
`record` debut is a partial counter-data-point: its opener states only the archive year
(1915) with no margin at all, so P_compound's double-qualifier construction doesn't apply —
worth noting as a new record-type variant (`record` may not carry the same
`previous_record_year`+margin bundle fields as `all_time_high`/monthly_low/monthly_high,
so the construction may not even be available to trigger this pattern for the new type).
**Last seen:** Jul 7 (6 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7).
Jul 8: Snowshoe, West Virginia `all_time_high` again — same station as Jul 7, one day
later, a different reading (90°F/July 4 vs. Jul 7's 89°F/July 3): "hottest daily maximum
in 52 years of records, 3°F above the 1986 mark" — same archive+margin double-qualifier
construction, 7th cycle. This time the pattern is NOT overcome: the close is
implied-consequence, not declarative (P_close failing — see that proposal), so the
draft grades only B+, unlike Jul 7's A- on the same station/type/mechanic. Useful
comparison point: P_compound alone doesn't cap a draft (soft cost), but stacking it with
a P_close-failing close compounds to a full grade below the same city's draft from the
day before.
**Last seen:** Jul 8 (7 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8).
Jul 9: Stevensville, Maryland `all_time_high` — "beating a record from 1934, by 2°F, in
101 years of data" — **the worst instance of this pattern yet**, stacking a third
qualifier (the named prior-record year, 1934) on top of the usual archive-span + margin
pair. Every prior instance stacked exactly two of the three available qualifiers; this
is the first to stack all three in one clause. Overcome by a clean declarative
buffer-failure close (see P_close), so it still soft-caps rather than hard-caps — same
pattern as every prior P_compound-plus-strong-close instance (Prudhoe Bay, Loxahatchee,
Snowshoe Jul 7).
**Last seen:** Jul 9 (8 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8, Jul 9).
Jul 10: Tepee Creek, Montana `all_time_high` — "hottest daily maximum in 39 years of
records, 4°F above the 2002 mark" — back to the standard double-qualifier form (not the
Jul 9 triple-stack escalation). This time NOT overcome: the close is implied, not
declarative (see P_close), so the draft grades only B+, the same
double-qualifier-plus-failing-close combination as Jul 8's Snowshoe. Both sub-forms of
this proposal (standard double, and Jul 9's triple-qualifier escalation) remain live.
**Last seen (pre-Jul-14):** Jul 10 (9 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7,
Jul 8, Jul 9, Jul 10).
Jul 14: Randolph, Utah `all_time_high` — "hottest daily maximum in 134 years of records, 3°F
above the 1893 mark" — standard double-qualifier form (archive span + margin), same sub-form
as Jul 10's Tepee Creek. Not overcome: the close is implied, not declarative (see P_close;
also see new proposal A7 for the same draft's separate phrase-echo concern), so the draft
grades only B+ — the same double-qualifier-plus-failing-close combination as Jul 8's
Snowshoe and Jul 10's Tepee Creek. Basrah's `absolute_extreme` draft this cycle is not
P_compound territory (single margin qualifier only, no archive-span field in the bundle).
**Last seen (pre-Jul-16):** Jul 14 (10 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7,
Jul 8, Jul 9, Jul 10, Jul 14).
Jul 16: Powderville, Montana `all_time_high` — "hottest daily maximum in 63 years of
records, 4°F above the 2002 mark" — standard double-qualifier form, 11th cycle. This time
overcome: the close is a declarative named-absence consequence (see P_close), so the draft
grades A- despite the compound opener — same soften-not-cap outcome as Loxahatchee, Snowshoe
Jul 7, Prudhoe Bay, and Stevensville's triple-stack. Oslo `hot10` carries no archive-span
field in its bundle (a daily-anomaly leaderboard type, not a record type) — not P_compound
territory, consistent with how absolute_extreme/cyclone/dust_event/air_quality_hazard types
have never triggered this pattern.
**Last seen (pre-Jul-17):** Jul 16 (11 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7,
Jul 8, Jul 9, Jul 10, Jul 14, Jul 16).
Jul 17: Deaver, Wyoming `all_time_high` — "hottest daily maximum in 111 years of records, 3°F
above the 1925 mark" — standard double-qualifier form, 12th cycle, and the longest archive span
this proposal has observed. Overcome: the close is a declarative verb-phrase consequence
("traps heat," see P_close), so the draft grades A- despite the compound opener — same
soften-not-cap outcome as every prior overcome instance. The 3 `absolute_extreme` drafts this
cycle carry no archive-span field (forecast-vs-threshold bundles, not record bundles) — not
P_compound territory, consistent with the established pattern.
**Last seen (pre-Jul-18):** Jul 17 (12 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8,
Jul 9, Jul 10, Jul 14, Jul 16, Jul 17).
Jul 18: Wausaukee, Wisconsin `all_time_high` — "hottest in 130 years of records, 4°F above the
1901 mark" — standard double-qualifier form, 13th cycle. Overcome: the close is a declarative
named-absence mechanism-failure ("without the lake bleeding it off first," see P_close), so the
draft grades A- despite the compound opener — same soften-not-cap outcome as every prior overcome
instance. Today's 2 `precipitation_extreme` drafts carry no archive-span field (event-total
bundles, not record bundles) — not P_compound territory, consistent with the established pattern.
**Last seen (pre-Jul-19):** Jul 18 (13 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8,
Jul 9, Jul 10, Jul 14, Jul 16, Jul 17, Jul 18).
Jul 19: W Allis, Wisconsin `all_time_high` — "hottest daily maximum in 76 years of records, 2°F
above the 1953 mark" — standard double-qualifier form, 14th cycle. Overcome: the close is
declarative ("overwhelms that buffer," see P_close), so the draft grades B+ despite the compound
opener — soften-not-cap holds, though the weaker/more generic verb than Jul 18's Wausaukee sibling
keeps it a notch below A-. Today's 3 `absolute_extreme` drafts carry no archive-span field
(forecast-vs-threshold bundles) — not P_compound territory, consistent with the established
pattern.
**Last seen:** Jul 19 (14 cycles: Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8, Jul 9,
Jul 10, Jul 14, Jul 16, Jul 17, Jul 18, Jul 19).

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`
record-type framing section:

> When stating a record: choose ONE qualifier per sentence — either the archive span ("23 years of
> records") OR the margin above the prior mark ("15°F above the 2020 mark"). Not both. Preferred
> form: "Beaver Dams, Utah hit 104°F on June 25 — 15°F above the previous record, set in 2020."
> Let the archive depth be implicit (the reader infers that a record being set means the archive
> was searched) or move it to sentence 2 as contrast. Stacking both in the same clause produces
> two half-punchlines; either one alone produces a full punchline.

**Expected impact:** Tighter record-type openers; B+ → A- path for drafts where mechanism is
already solid. Immediate two-observation confirmation within a single cycle suggests the
double-qualifier is a prompt-level default, not a one-off. Affects all_time_high, monthly_low,
monthly_high, country_record signal types where both archive depth and margin are available.

**Status:** Drafted. Awaiting human implementation. 14 cycles (Jun 28, Jun 29, Jun 30, Jul 2, Jul 4, Jul 7, Jul 8, Jul 9, Jul 10, Jul 14, Jul 16, Jul 17, Jul 18, Jul 19), 2 sub-forms live (standard double-qualifier, and Jul 9's triple-qualifier escalation). One of the two highest-leverage unimplemented proposals alongside P_close, now that P9/P_dust/P_tier have all closed their tracking.

### A7 — Location reuses its own prior closing construction across different draft events (promoted from awaiting-evidence)

**Observed:** 2026-07-14 — Randolph, Utah `all_time_high` closes with "high-desert elevation
normally bleeds off the heat that pools across the Great Basin floor." This same station's Jun 24
corpus draft, a `monthly_high` (B+), closed with "normally blunts the heat." Both share the
identical "normally [verb]s the heat" shape and the identical implied-not-declared P_close gap, on
the same city, 20 days apart, across two *different* record types. Filed as awaiting-evidence item
A7 with an explicit promotion bar: "2+ locations show this pattern."

**2026-07-18 — 2nd location confirms, promoted to active.** Anchorage, Alaska's fresh
`precipitation_extreme` draft closes with "compress moisture into short, intense bursts" — the
same underlying "wring-out/compress-moisture...bursts" construction this exact station has now
used **three times**: Jun 26 ("wring out moisture in compressed bursts," graded B, mechanism-only
failing), Jul 9 ("wring out moisture in concentrated bursts," graded B, P_close FAILING — "one
word from Jun 26's own Anchorage draft" per that cycle's own grading), and today ("compress
moisture into short, intense bursts," graded B, P_close FAILING again). Each individual instance
still clears a B/B+ floor on the strength of a genuinely correct orographic mechanism — this
isn't a factual or Wodehouse problem — but the writer is visibly reaching for its own prior
sentence shape rather than composing fresh phrasing for what is, each time, an actually-new
storm event. Two distinct locations (Randolph: record-type system-clause reuse; Anchorage:
precipitation-mechanism close reuse) now confirm the underlying pattern — the writer's own prior
phrasing calcifying into a per-location default — meeting A7's stated 2-location promotion bar.

**Cycles observed:** 4 (Jun 26 and Jul 9 — Anchorage, retroactively relevant; Jul 14 — Randolph,
A7 filed; Jul 18 — Anchorage's 3rd instance, promotion trigger) across 2 locations (Anchorage ×3,
Randolph ×1).
**Last seen:** Jul 18.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`, in
the memory-usage guidance section (near where the `recent_categories` 24h cooldown is already
described):

> When the bundle's location has appeared in a prior corpus draft, do not reuse that prior draft's
> system-clause or closing-sentence construction verbatim or near-verbatim — even when the
> underlying physical mechanism genuinely applies again. Randolph, Utah's "normally blunts the
> heat" (Jun 24) → "normally bleeds off the heat that pools..." (Jul 14), and Anchorage, Alaska's
> "wring out moisture in compressed bursts" (Jun 26) → "...in concentrated bursts" (Jul 9) →
> "compress moisture into short, intense bursts" (Jul 18), are the same mechanism restated in
> near-identical language two or three times. The mechanism can recur; the sentence shape
> shouldn't. When re-describing a familiar mechanism for a repeat location, vary the vehicle (a
> different physical detail, a different comparison, or a named consequence instead of another
> mechanism restatement) rather than a synonym-substituted copy of the prior sentence.

**Expected impact:** Prevents formulaic drift at the per-location level — the same failure class
P6 (fire opener) and P9 (precipitation opener) addressed at the per-category level before their
fixes shipped, this time one level down (the closing construction, not the opener) and keyed by
place rather than category. Currently only observed at a B/B+ ceiling — neither Anchorage's nor
Randolph's instances have graded below B+ — so this isn't hard-capping grades today, but the
pattern is accelerating (Anchorage's 3rd instance inside 3 weeks) and risks becoming an
unexamined default the way P6's fire-opener template did before its fix, if left unaddressed.

**Status:** Promoted from awaiting-evidence (A7) 2026-07-18 — Anchorage's 3rd instance is the 2nd
location confirming the pattern, meeting A7's own stated 2-location promotion bar. Awaiting human
implementation.

### A8 — `absolute_extreme` opener-skeleton convergence + stranded/reused declarative clauses (promoted from awaiting-evidence)

**Observed:** 2026-07-17 — two related but distinct convergence signals surfaced in the same
cycle, both specific to `absolute_extreme`. (1) **Same-cycle opener-skeleton convergence:** all 3
fresh drafts shared an identical sentence-1 shape — "[City], [Country] is forecast to hit XX.X°C
(YYY°F) [on Date/today] — [above/just inside] the 47°C threshold where..." (2) **Reused
declarative clause:** Basrah's mid-sentence-1 qualifier, "shade and stillness stop being enough,"
near-verbatim echoed Jul 10 Ahvaz's A- close, "shade and rest alone stop being enough." Basrah's
draft also introduced a third, related shape: its one genuinely declarative move was **stranded**
mid-sentence-1 rather than placed in the closer, while the actual closer was a hedged,
non-declarative form — graded B+ on that basis, distinct from P_close's usual implied-vs-
declarative gap (the declarative move exists, it's just misplaced).

**2026-07-19 — both remaining axes clear their promotion bar.** Al Basrah, Iraq's fresh draft
repeats Jul 17 Basrah's stranded-mechanic shape exactly: "shade, hydration, and rest stop being
adequate buffers" is buried as a sentence-1 tail qualifier, while the tweet's actual last sentence
("Nearby Basrah is forecast to hit 50.6°C the same day") is a bare peer-comparison fact with no
mechanism or consequence — 2nd instance of the stranding shape, different city, 2 days apart. The
same buried clause is also the **3rd instance** of the reused survivability-threshold construction:
"shade and rest alone stop being enough" (Jul 10, Ahvaz) → "shade and stillness stop being enough"
(Jul 17, Basrah) → "shade, hydration, and rest stop being adequate buffers" (Jul 19, Al Basrah, now
expanded to a 3-item list). Meanwhile the opener-skeleton axis gets both confirmation and
counter-evidence in the same cycle: Ahvaz [6] and Al Basrah [8] both repeat the "forecast to hit
XX°C — above the 47°C threshold where..." skeleton (a 2nd cycle showing it, after Jul 17's
same-cycle 3-instance debut — now cross-cycle, not just within one day), while Ahvaz/Bandar-E
Mahshahr [9] breaks from it entirely with a two-city comparison construction instead. All three
Jul 19 `absolute_extreme` drafts stay clean of P_tier (the confirmed post-fix "threshold where
[region] does X" world-knowledge form, not an internal band/tier label).

**Cycles observed:** 2 (Jul 17, Jul 19) across all three tracked shapes. Reused-clause axis: 3
instances (Jul 10, Jul 17, Jul 19) across 2 cycles. Stranded-mechanic axis: 2 instances (Jul 17,
Jul 19) across 2 cycles. Opener-skeleton axis: now observed across 2 distinct cycles (Jul 17
same-cycle ×3, Jul 19 ×2 of 3), plus 1 clean counter-instance same cycle (Ahvaz/Bandar-E Mahshahr).
**Last seen:** Jul 19.

**Proposed fix (PROMPT LANGUAGE — surgical):** Add to `src/two_bot/prompts/writer_prompt.py`'s
`absolute_extreme` framing section, near the existing "delete the system clause" test:

> When the second sentence's genuinely declarative move (a named-absence consequence, a
> survivability-threshold statement) is embedded as a sentence-1 qualifier rather than placed in
> the closer, MOVE it to the closer — don't let the tweet end on a bare comparative fact ("Nearby
> [City] is forecast to hit YY°C the same day") when a real consequence is available elsewhere in
> the draft. Separately: "shade and rest/stillness/hydration stop being enough/adequate buffers"
> has now been used verbatim or near-verbatim on 3 different cities across 3 different cycles —
> retire it as a reusable phrase and vary the specific vehicle (name a different failing buffer,
> or state the physiological consequence directly, e.g. "the body's cooling mechanisms fail
> faster than they can recover," per Jul 14's Basrah) each time the mechanism recurs. Finally: the
> "[City] is forecast to hit XX.X°C — above the 47°C threshold where..." skeleton is now a
> repeating default; alternate with a location-led or stakes-led opener (see P6's fire-opener
> precedent) at least some of the time.

**Expected impact:** Same class of fix as P6 (fire opener) and P9 (precipitation opener) applied
to `absolute_extreme`'s two failure axes plus a third (clause placement) unique to this type.
Currently caps at B+ rather than hard-capping (like P_tier did pre-fix), so the ceiling lift is
B+ → A- for drafts where the mechanism and declarative move are both already present but
misplaced or reused — a comparatively cheap fix given the underlying signal quality is already
there in every observed instance.

**Status:** Promoted from awaiting-evidence (A8) 2026-07-19 — both the stranded-mechanic axis (2
instances) and the reused-clause axis (3 instances) clear the standard 2-instance promotion bar
this precedent has used since A3. The opener-skeleton axis has weaker but growing cross-cycle
evidence (2 cycles, with a clean counter-instance the same day) — tracked alongside the other two
axes under this same proposal rather than split out, since all three are specific to
`absolute_extreme`'s convergence pattern. Awaiting human implementation.

~~### P_precip_floor — Precipitation quality floor~~ → **[Archived 2026-07-02 — see Resolved section]**

### ~~P6~~ — Fire template convergence — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** 2026-05-13 first graded two-bot cycle — all 3 fire drafts (Mali,
Campeche, Mongolia) used the identical sentence-1 structure: *"A fire in
[location] is radiating X MW of heat, detected by satellite at N% confidence."*
The writer defaults to the most-stated form when the bundle is signal_kind=fire
without historical_context, and the prompt's existing fire exemplar (#4) further
reinforces the template. The 24h category cooldown shipped in PR #85 catches
this across cron runs but not within a single cycle.

**Cycles observed:** May 13 (1 cycle; 3 of 3 fire drafts identical sentence-1).
**Last seen:** 2026-05-13.

**Resolution:** New paragraph in `writer_prompt.py` IF-historical_context-IS-EMPTY
section directly after the FRP intensity tier paragraph. Names 4 alternative
sentence-1 forms (lead-with-location, lead-with-seasonal-frame, lead-with-tier-word,
lead-with-stakes-or-scale-anchor) with full example tweets for each. Closes by
banning the default opener when `recent_categories` already contains "fire" within
24h, and tells the writer to ask whether the bundle is actually extraordinary
enough to ship if no alternative form works.

**Status:** SHIPPED in PR #85 second commit. Empirical test: next cron run that
produces 2+ fire drafts in the same cycle — do they show structural variety?

### ~~Chuuk ceiling — "expository → punch"~~ — **SHIPPED 2026-05-12 (PR #85)**

**Observed:** 2026-05-13 grader noted that the Chuuk monthly_high draft was the
ceiling at B (not A-). Clean data, 76-year record, °C+°F, specific date — but
second sentence was "expository (Pacific warm pool context) rather than a
punch." The system clause described the geography without paying off the data.

**Cycles observed:** May 13 (1 cycle; identified as ceiling-class).
**Last seen:** 2026-05-13.

**Resolution:** Augmented THE SIGNATURE MOVE section's bullet-2 with the
expository-vs-punch distinction. Explicit B-vs-A example pair using the Chuuk
case ("Chuuk sits in the Pacific warm pool" → expository B; "Chuuk anchors the
Pacific warm pool — the engine of the global atmosphere; small May reading
shifts here propagate downstream" → punch A). New "delete the system clause"
test: if removing your second sentence leaves the reader thinking "so what?",
load-bearing. If it leaves them thinking "oh, fair enough", expository.

**Status:** SHIPPED in PR #85 second commit. Empirical test: next graded cycle —
do system clauses do work (consequence/contrast/causal/rate) rather than just
describing geography?

## Awaiting evidence

These need more cycles before promotion to active proposals or retirement.

### A1 — Era_anchors prune impact (Apr 26) — superseded by architecture change

43 politically-charged entries removed from `data/era_anchors.json` on 2026-04-26. The
Apr 27 cycle had one political-anchor draft (Jacobabad / Elon Musk). Whether the prune
eliminated leakage was the watch condition — but this is now moot because generator.py
(which used era_anchors.json) is dead since 2026-05-04. The two-bot writer has its own
`memory.used_era_anchors` tracking. Watch for: era anchor quality in two-bot record
drafts once they reach pending. If any politically-charged anchor appears, that's a
separate curation path to investigate in the two-bot writer.

### A2 — Two-bot writer sample-size baseline (replaces v2.5 sample-size question)

**Updated 2026-05-19:** Two-bot baseline now measurable across two graded cycles (May 13:
0/4 = 0%; May 19: 3/14 = 21%). Cumulative: 3 A / 18 drafts = 17% A-rate on first two-bot
graded drafts. First A-grades are coral_bleaching (3 of 3 A-grades came from new category
on 2026-05-19). Fire and monthly_high categories have not yet produced an A-grade in the
two-bot era. Voice engine history (v2: 43%; v2.5: 9%) remains reference only — pipeline
dead.

**Updated 2026-05-25:** Five consecutive graded cycles (May 20, 22, 23, 24, 25) produced
0 fresh drafts. Queue static since 2026-05-18T15:52Z (~7 days). Two-bot A-rate baseline
unchanged: May 13 0/4 = 0%; May 19 3/14 = 21%; cumulative 3A / 18 = 17%. The 0.9.0.0
release (2026-05-22) wired all 23 sources through the evidence contract for the first time
— `stage="evidence_contract"` suppression kills are now possible on every signal type and
are unverified empirically. A non-trivial kill count here would explain queue stagnation
without invoking seasonal quiet. Next measurement when queue resumes.

**Watch for:** whether fire category closes the gap between the May-13 0% and the coral
batch's A-grade-producing range. Whether Wodehouse violations re-emerge as more categories
are added. Whether the new critic stage (Gemini 2.5 Pro, PR #120) is contributing to or
suppressing A-grade candidates before they reach pending.

~~### A3 — Mediterranean SST threshold calibration gap (P_dust analog)~~ → **Promoted 2026-07-01 — see Active proposals, P_tier**

Filed Jun 23 on a single Mediterranean SST instance ("exceeds the 2.5°C tier threshold..."), with
an explicit promotion condition ("if 2+ cycles observed"). 2026-07-01 cleared that bar in one
cycle: 3 fresh instances across `absolute_extreme` (×2) and `fire_footprint`, plus the
already-graded Mediterranean SST carry-over. Broader than originally scoped — not just NOAA CRW
SST tiers but any internal scoring-tier/threshold label leaking into copy across at least 3
signal types. Full current writeup, evidence, and proposed fix now live under **P_tier** in
Active proposals above.

### A4 — Signal-kind self-naming leaks into `air_quality_hazard` copy, post-P_tier-fix

**Observed:** 2026-07-07 — Riyadh, Saudi Arabia `air_quality_hazard` (created
2026-07-07T14:56:03Z, ~9.8h **after** PR #386 merged the detection-plumbing ban): "This is
a PM2.5 signal, not dust; the Arabian interior's summer heat suppresses mixing and traps
fine particles close to the surface." "This is a PM2.5 signal" names the bot's own
`signal_kind` categorization (`air_quality_hazard` vs. `dust_event`) rather than describing
a fact a reader could verify about the world — the word "signal" is the tell; no lay
reader would disambiguate smog this way unprompted. This is a close lexical cousin of the
tier-jargon violation P_tier tracked and PR #386 just banned, but a different shape:
disambiguating the bot's own event-category label, not citing a severity band/threshold/
trigger definition. The shipped rule's own test ("is this a fact about the WORLD, or a
fact about this bot's configuration?") answers "configuration" here just as cleanly as it
does for tier-jargon, but the rule's actual wording (`band_label`, score thresholds,
trigger definitions) doesn't explicitly name signal-kind self-disambiguation as a banned
category — this may be a gap in the fix's coverage, or may simply need one more cycle to
confirm it's a real pattern rather than a single stochastic instance.

**Cycles observed:** 1 (Jul 7).
**Last seen:** Jul 7.
Jul 8: **does not recur.** Today's 2 PM-signal drafts (Riyadh `dust_event`, Riyadh
`air_quality_hazard`, same city/day) both cite their WHO multiples cleanly with no
signal-kind self-naming — the `air_quality_hazard` draft's close ("this is a basin-scale
loading, not a street-corner spike") is superficially similar in cadence to Jul 7's "This
is a PM2.5 signal, not dust" but is a genuinely different construction: it clarifies
model-grid resolution honesty (a verifiable fact about the data), not the bot's internal
`signal_kind` category. Useful negative evidence against a 2nd real instance — worth not
conflating the two constructions in future grading (see `docs/DRAFT_CORPUS.md` Jul 8
entry for the explicit distinction). Still 1 cycle; not promoted.

**Watch for:** a 2nd instance of a draft naming its own `signal_kind`/category/bundle-type
label (words like "signal," "event," "bundle," "this is a/an [X]-type reading" used to
self-classify rather than describe a physical phenomenon) in `air_quality_hazard`,
`dust_event`, or any other signal type with an adjacent sibling category the writer might
feel a need to disambiguate from. **Promote to an active proposal if 2+ cycles are
observed**, per the same promotion rule A3 used before becoming P_tier. If it recurs, the
fix is almost certainly a one-line addition to the existing "DETECTION PLUMBING IS NOT A
FACT" rule in `writer_prompt.py` (PR #386) rather than a new rule — extending its examples
to cover signal-kind self-naming explicitly.

### A5 — `cyclone_land_threat` packs two wind-speed values without marking the time-shift between them

**Observed:** 2026-07-08 — Typhoon Bavi, the corpus's first `cyclone_land_threat` draft:
"Typhoon Bavi, packing 125 kt winds, is forecast to pass within about 42 NM of Ishigaki,
Japan in roughly 60 hours — at 110 kt per the JTWC track." Two different wind values ride
one sentence — 125 kt (the current, observed intensity that correctly leads per move 4)
and 110 kt (the forecast intensity at the moment of closest approach, ~60 hours out) —
with no explicit marker that the second number is a different point in time. A reader
who isn't already tracking the storm could read this as an internal contradiction (which
number is right?) rather than a forecast weakening trend. The bundle fields and the
forecast-tense discipline are both used correctly; this is a phrasing/clarity gap, not a
rule violation.

**Cycles observed:** 1 (Jul 8) — also this signal type's corpus debut, so there is no
prior instance to compare against.
**Last seen:** Jul 8.

**Watch for:** a 2nd `cyclone_land_threat` draft that either (a) repeats the same
unmarked dual-wind-value construction, or (b) resolves it naturally (e.g., "now 125 kt,
forecast to weaken to 110 kt by closest approach"). **Promote to an active proposal if
2+ cycles show the unmarked-dual-value form.** If it recurs, the likely fix is a small
addition to the cyclone bundles' move 4 guidance: when both `current_wind_kt` and a
forecast-time wind value are cited in the same sentence, mark the time-shift explicitly
("now... by the time it's closest to Ishigaki...") rather than stacking two bare numbers.

### A6 — Permafrost-carbon fire mechanic reuses near-verbatim phrasing across different locations/events

**Observed:** 2026-07-11 — two independent phrase-level repeats surface in the same cycle,
both drawn from the fire category's most reliable A-grade path (the permafrost-carbon
mechanic, first established Jun 25 Siberia and confirmed across Jul 3/Jul 5/now Jul 11 —
6 corpus instances total). (1) Western Siberia fire's close — "Western Siberia's summer
fire season is burning across peat that took centuries to accumulate" — is a near-verbatim
repeat of Jul 3's Canadian Arctic near-duplicate close, "burns into organic soil layers
that took centuries to accumulate" (same "took centuries to accumulate" clause, different
location/event, 8 days apart). (2) Interior Alaska fire's close — "doesn't just consume
trees — it burns into the organic layer above the frozen ground" — reuses the exact
contrastive-negation construction ("doesn't just [verb] — it [verb]s...") from Jul 5's
eastern Siberia draft, "doesn't just burn the surface — it thaws the ground beneath it" (6
days apart, different location). Distinct from the already-tracked "duplicate-generation"
operational anomaly (same bundle/event re-issued under a new draft_id, e.g., Ft Green,
Basrah, Canadian Arctic same-day near-duplicates): both of today's repeats are genuinely
different fire events (different location, date, MW reading) reusing the writer's own
prior phrasing for a structurally similar but distinct signal. Risk: the mechanic that has
been this plan's most reliable fire-category A-grade path (6 corpus instances, all B+/A-)
may be curdling into its own stock phrase bank exactly the way P6's original opener-template
convergence did in May, just one level down the sentence (the close, not the opener).

**Cycles observed:** 1 (Jul 11) — 2 independent phrase-level recurrences in the same cycle,
each with a single prior confirmed instance (Jul 3, Jul 5 respectively).
**Last seen:** Jul 11.

**Watch for:** a 3rd instance of either construction ("...that took centuries to
accumulate" / "doesn't just X — it Y") applied to a permafrost-carbon fire mechanic on a
different location. **Promote to an active proposal if 2+ cycles show either construction
recurring**, per the same promotion rule A3/A4/A5 used. If it recurs, the likely fix is a
small addition to the fire section of `writer_prompt.py`: when the permafrost-carbon
mechanic applies, name 2-3 alternative closing constructions (e.g., a specific downstream
consequence — methane release, decades-scale recovery time — instead of restating the
carbon-age fact in the same shape every time) so the mechanic doesn't calcify into a single
reusable sentence the way this plan's other shipped fixes (P6, P9) addressed at the
opener level.

~~### A7 — Location reuses its own prior system-clause construction across different draft events~~ → **Promoted 2026-07-18 — see Active proposals, A7**

Filed Jul 14 on a single location (Randolph, Utah, reusing its own `monthly_high`→`all_time_high`
system-clause across 2 draft events), with an explicit promotion condition ("2+ locations show
this pattern"). 2026-07-18 cleared that bar: Anchorage, Alaska's fresh `precipitation_extreme`
draft is the 2nd location, reusing its own closing-mechanism phrasing across 3 draft events (Jun
26, Jul 9, Jul 18). Full current write-up, evidence, and proposed fix now live under **A7** in
Active proposals above.

~~### A8 — `absolute_extreme` opener-skeleton convergence + reused survivability-threshold clause~~ → **Promoted 2026-07-19 — see Active proposals, A8**

Filed Jul 17 on a single cycle's 3-instance opener-skeleton convergence plus a 2-instance reused
declarative clause, with an explicit promotion condition ("2+ cycles show either axis recurring").
2026-07-19 cleared that bar on both the reused-clause axis (3 instances: Jul 10, Jul 17, Jul 19)
and a newly-identified stranded-mechanic axis (2 instances: Jul 17, Jul 19) from the same signal
type's convergence pattern. Full current write-up, evidence, and proposed fix now live under
**A8** in Active proposals above.

## Resolved (archive)

History of fixes that landed or became obsolete — added when a failure mode either held
for 3+ cycles without appearing, or when the target code was retired.

### [Archived 2026-07-03, Re-activated 2026-07-04] P9 — precipitation_extreme opener template convergence + restate-math

Archived Jul 3 after 3 consecutive fresh-draft cycles without a `precipitation_extreme` draft
(Jul 1, Jul 2, Jul 3), with an explicit note that this was absence-of-opportunity, not a
confirmed fix, and that the pattern was "very likely to recur on the very next instance." It did
— see Active proposals above for the reopened entry with Jul 4's confirming evidence.

### [Archived 2026-07-02] P_precip_floor — Precipitation quality floor

Last observed Jun 29 (Amsterdam [6] A-, 4.7% margin, wet-climate — voice execution offset the
weak signal but the structural gap was logged). 3 consecutive fresh-draft grading cycles since
without a qualifying observation: Jun 30 (2 precipitation_extreme drafts, but Astana's thin
margin was in an explicitly arid steppe location — criterion (b) wet-climate not met); Jul 1 (no
precipitation_extreme drafts at all); Jul 2 (no precipitation_extreme drafts at all) — meets the
3+ runbook threshold. The fix (self-kill gate in writer_prompt.py) remains unimplemented; the
absence reflects signal mix, not a resolved failure mode. Reopen if a `precipitation_extreme`
draft with <10% margin above the prior record in a wet-climate location (>800mm/yr, maritime, or
tropical) reappears in pending.

### [Archived 2026-06-17] P8 — Snow/extreme record: ratio-as-punchline unused

Last observed May 19 (1 cycle; 2/2 snow_extreme drafts). 4 fresh-draft grading cycles
without snow_extreme in the queue (Jun 7, Jun 13, Jun 15, Jun 17) — exceeds 3-cycle
threshold. No new snow_extreme drafts have appeared in the post-0.9.6.0 triage era;
the absence may be seasonal or score-gate. Reopen if snow_extreme drafts with ≥2×
ratio appear and still don't land the ratio as punchline.

### [Archived 2026-06-15] P7 — Coral opener formula convergence

Last observed: May 19 (8 of 9 coral drafts used accumulation formula). Jun 15 retroactive
batch: 2 coral drafts (Gilbert Islands, Nauru) both used alternative opener forms — colon-lead
and possession form respectively. Neither used the banned accumulation sentence. 3+ graded
cycles (Jun 7 n/a, Jun 13 n/a, Jun 15 counter-evidence) without observation; resolved. If the
formula reappears in future coral batches, re-open with the original fix spec (3 alternative
sentence-1 forms + DHW persistence exemplar from the May 19 corpus).

### [Archived 2026-06-21, 2nd archiving] P_new — Cold-record quality floor

Re-activated Jun 13 (Red Dog Mine, Alaska: 17yr archive, 1°F margin, above Arctic Circle —
all three kill criteria met; operator rejected). 3 consecutive fresh-draft cycles since then
without cold-record drafts (Jun 15 retroactive: no cold-record; Jun 17: dust_event only;
Jun 18: precipitation_extreme only) — meets the 3+ runbook threshold for archiving.
Reopen if `monthly_low` or `country_low` drafts with (a) < 20yr archive, (b) < 2°F margin,
(c) cold-climate location reappear in pending. The fix (self-kill gate in writer_prompt.py)
remains unimplemented; the absence is seasonal/triage-upstream, not a resolved failure mode.
Chesnee SC (35yr, 7°F, SE US) remains the counter-example: writer correctly passes strong signals.

### [Archived 2026-06-09, Re-activated 2026-06-13] P_new — Cold-record quality floor

Archived Jun 9 after 6 consecutive fresh-draft cycles without recurrence (May 15–19, Jun 7).
Re-activated Jun 13: Red Dog Mine, Alaska monthly_low (19°F, score 80, 17yr archive, 1°F
margin, above Arctic Circle) hit pending — all three kill criteria met. Archive note
condition ("Reopen if cold-record drafts with shallow archive + trivial margin reappear")
was satisfied. Full proposal text now in Active proposals section above. Chesnee SC
monthly_low (Jun 10, 35yr archive, 7°F margin, SE US) remains the clear counter-example
that the proposal correctly does NOT kill.

### [Archived 2026-05-12] P2 — Widen plant-comparison regex adjective allowlist

Last observed: Apr 27 (1 draft; "a commercial nuclear reactor"). Target code
`src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead since 2026-05-04. Proposal
cannot fire in the live two-bot pipeline. If plant-comparison failures emerge in two-bot
output, open a new proposal targeting `src/two_bot/prompts/writer_prompt.py`.

### [Archived 2026-05-12] P3 — Widen opener-formula verb list

Last observed: Apr 27 (1 draft; "pushing" not in verb allowlist). Target code
`src/voice/generator.py::_STOCK_FORMULA_PATTERNS` is dead since 2026-05-04. Proposal
cannot fire in the live pipeline. If banned-opener variants emerge in two-bot fire drafts,
open a new proposal against `src/voice/safety.py` (the safety pipeline still runs) or
`src/two_bot/prompts/writer_prompt.py`.

### [Archived 2026-05-12] P5 — Add stranded-mechanic warning to fire prompt addendum

Last observed: Apr 27 (3 drafts; mechanics buried in throat-clearing). Target code
`src/voice/generator.py::_CATEGORY_PROMPTS["fire"]` is dead since 2026-05-04. The
underlying concern (don't bury the punchline in setup) is covered by P4's Wodehouse rule
in the updated writer_prompt.py proposal.

## Daily agent runbook

The recurring grading agent fires every day at 15:00 UTC (8 AM Pacific PDT). Its job is to refine THIS plan, not implement. Per-run protocol:

1. Read these docs (the framework):
   - `docs/IMPROVEMENT_PLAN.md` (this doc — the active state)
   - `docs/DRAFT_CORPUS.md` (longitudinal grading archive)
   - `docs/QUALITY_TREND.md` (A-rate-by-cycle metric)
   - `brand/HUMOR_RESEARCH.md` (humor theory + voice mechanics)
   - `brand/VOICE.md` (voice spec)
   - `BRIEFING.md` (project state)

2. Pull pending drafts from Gist `06c02c97ffc0d11458687f1ed998d9e5`.
3. Grade each draft on the A-F rubric matching the corpus methodology.
4. Apply the humor-research lens (named mechanic operating, Wodehouse rule, stranded mechanics, Sonnet-rewrite-bypass NOTE: intentional per user).
5. Append a new dated section to `docs/DRAFT_CORPUS.md` (top of file, just below the header).
6. Append a new row to `docs/QUALITY_TREND.md` A-rate table.
7. **Refine THIS plan** (`docs/IMPROVEMENT_PLAN.md`):
   - For each active proposal, if a new failure was observed → increment "Cycles observed" count, update "Last seen" date.
   - If a new failure mode emerged that doesn't fit existing proposals → add new proposal with full template (Observed / Cycles / Last seen / Proposed fix / Expected impact / Status).
   - If an active proposal hasn't been observed for 3+ cycles → move it to "Resolved (archive)" with a one-line note.
   - Re-order active proposals by current leverage (observation count × recency).
8. Bulk-reject any pending drafts older than 48 hours that contain real-time-baked content (per the 2026-04-26 staleness policy).
9. Commit to a feature branch `daily-plan-YYYY-MM-DD`, push, open a PR titled "Daily plan refinement YYYY-MM-DD".
10. Print to stdout: A-rate, gap from bar, top 3 active proposals (numbered).

**Hard constraints:**
- DO NOT push to main. Branch + PR only.
- DO NOT modify code (`src/**`, `tests/**`).
- DO NOT modify spec docs (`brand/VOICE.md`, `brand/MESSAGING_ARCHITECTURE.md`, `brand/HUMOR_RESEARCH.md`, `brand/EXEMPLARS.md`, `brand/VIRALITY_RESEARCH.md`).
- DO NOT modify `data/era_anchors.json` content — only the `audit_history` field in `_meta` if logging.
- DO NOT modify regex (`_STOCK_FORMULA_PATTERNS`) or any prompt strings.
- DO NOT propose architectural changes (new modules, tool swaps, new data sources).
- DO NOT propose Sonnet-evaluator-rewrite bypass — user has confirmed (2026-04-27) it's intentional design.
- DO NOT skip a run because the queue is empty — append a "no fresh drafts" entry to the corpus instead, with a note on why this might have happened (cycles haven't fired, all auto-published, etc.).

**Allowed file edits:**
- `docs/DRAFT_CORPUS.md` (append new sections)
- `docs/QUALITY_TREND.md` (append rows)
- `docs/IMPROVEMENT_PLAN.md` (refine in place)
- Gist state (mark stale drafts as rejected)

## How the human operator uses this plan

- **Read on a schedule** (when a daily PR lands): scan the active-proposals top 3, pick what to implement.
- **Implement together with Claude in a session.** Reference this plan; the proposal entry has the full fix outlined. Move the entry to "Resolved" once the fix ships and the next 3 cycles confirm the failure mode is gone.
- **Override the plan when you have better information.** The daily agent works on what the corpus shows. If you see something the corpus hasn't surfaced yet, add it as a proposal directly (or override priorities).
- **Don't merge daily PRs blindly.** They're docs only, but bad observations can poison future runs. Skim before merging.
