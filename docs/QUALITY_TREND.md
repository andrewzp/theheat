# Quality Trend & Rejection Log

Two views of the same thing: **are the bot's tweets getting better over time, or not.**

## The resumption bar

> **Posting resumes when the majority of corpus-graded drafts in a cycle earn A grades.**
> Set 2026-04-26. Posting paused until then.

We grade drafts on an A through F rubric in `docs/DRAFT_CORPUS.md` (the longitudinal corpus archive). This file pulls the headline metric out of every grading cycle so trend is visible at a glance, plus logs rejection events so the "what got cut" history is traceable.

## A-grade rate by cycle

| Date | Drafts | A | B | C | D/F | A-rate | ≥50%? | Notes |
|------|-------:|--:|--:|--:|---:|------:|:-----:|-------|
| 2026-04-24 | 35 | 3 | 6 | 6 | 20 | **9%** | ✗ | Pre-voice-engine-v2 baseline. Most rejects were continent-only locations + "powers N homes" formulas. |
| 2026-04-25 | 7 | 3 | 3 | 1 | 0 | **43%** | ✗ | First post-v2 cycle. Largest single jump. Era anchors landing for the first time. |
| 2026-04-27 | 11 | 1 | 5 | 1 | 4 | **9%** | ✗ | Regression. Banned-formula opener variants returned via Sonnet rewrite path. Era anchors over-deployed. Plus one political-anchor (Elon, since pruned). Humor-lens evaluation surfaced what's failing. |
| 2026-04-29 | 3 | 0 | 2 | 0 | 0 | **0%** | ✗ | Three records, all using era anchors — third cycle with this pattern. User direction same day: park era anchors at 1-in-10. Voice engine v3 shipped: gate + addendum-mismatch fix + SYSTEM_PROMPT vehicle-agnostic rewrite. Next 3 cycles will show whether the gate empirically works. |
| 2026-05-12 | 0 | — | — | — | — | **—** | ✗ | No pending drafts (queue empty). All four production kills diagnosed and fixed: PR #82 (station-name regex for `4 NE` + ANG suffix), PR #80 (FRP bundle-side rounding), PR #82 (ocean_sst User-Agent header), PR #82 (river_gauges graceful degradation). PR #76 also added writer-side length-cap retry + KILL; PR #82 added JSON-parse retry + KILL. The 18:39 UTC alerts run is the first cycle against the fixes — first chance for fresh drafts to reach pending under the new voice + guardrails. Andrew also manually rejected Mankato cold record 2026-05-11 with voice direction: "defensive 'A record is a record' closer" (now banned via PR #74 HARD RULE). |
| 2026-05-13 | 4 | 0 | 1 | 3 | 0 | **0%** | ✗ | First graded two-bot cycle. 3 fire drafts (Mali, Campeche, Mongolia) all used identical formula opener + seasonal-explanation structure — fire template convergence identified as new failure mode (P6). Chuuk FSM monthly_high (76-year record) is the one B: clean data, no Wodehouse violation, but expository second sentence instead of a punchline. P3 self-kill failure not observed (positive). FRP bundle rounding (#80) confirmed working (309.6, 364.7, 307.6 MW values clean). |
| 2026-05-14 | 5 | 0 | 1 | 4 | 0 | **0%** | ✗ | 4 carry-overs from May 13 (grades unchanged: 1B/3C) + 1 new monthly_low (Bethel, ME — 16yr archive, 1°F margin) graded C. Cold-record quality floor identified: writer over-passes shallow-archive cold records that fail the editorial bar Andrew established (Mankato reject May 11). No named mechanics across all 5 drafts. P5 confirmed in two-bot context for 4th consecutive cycle (Apr 25, Apr 27, May 13, May 14). P6 empirical test still pending (fire drafts pre-date PR #89 fix). |
| 2026-05-15 | 10 | 1 | 5 | 4 | 0 | **10%** | ✗ | First coral_bleaching cycle (8 of 10 drafts); 1 fire (BC, P6 fix confirmed — different opener); 1 monthly_low (Bethel Maine B-). Galapagos A- = first A-grade in two-bot corpus (ratio framing + buffer-failure system clause). 7/8 coral drafts identical two-sentence template → P7 added. ~~P2~~ FRP rounding moved to Resolved (2 clean cycles). ~~P3~~ fire self-kill 3rd cycle without observation (approaching Resolved). P5 (name humor moves) now 4 cycles evidence. |
| 2026-05-16 | 10 | 1 | 4 | 5 | 0 | **10%** | ✗ | First coral_bleaching cycle. 8 coral drafts; 7 template-converge on DHW-explanation structure (new failure mode P7). Galapagos earns A- (24.5°C-weeks = double mortality threshold; cold upwelling buffer framing = ecosystem incongruity). Austral Islands B+ (geographic expansion framing). BC fire breaks formula opener — P6 fix confirmed empirically. No Wodehouse violations. No P3 fire self-kills (2nd consecutive). 10 new drafts; 4 carryovers from May 13 not re-counted. |
| 2026-05-17 | 14 | 1 | 7 | 6 | 0 | **7%** | ✗ | 14 pending: 4 carry-over fire/record from May 12-13, 1 monthly_low (Bethel Maine), 1 fire (BC), 8 coral_bleaching (first appearance of signal type). Single A-: Galapagos coral (24.5°C-weeks, double mortality tier; cold-upwelling incongruity + "stress accumulates fast" deadpan closer). 3 B+: Madagascar coral + Austral Islands coral (location-specific second sentences doing real work) + Chuuk carry-over. DHW explanation convergence: 5 of 8 coral drafts use near-identical second-sentence explanation by draft [10]; new failure mode → P7 added. BC fire [6] confirms PR #85 opener-variety fix working but "today" baked in (stale). Fire carry-overs [1]/[2]/[4] also stale (4-5 days; operator-reject needed). P5 cycles updated (4 cycles). F3 critic (PR #120) now in pipeline; unclear whether coral batch passed through it. |
| 2026-05-18 | 12 | 1 | 7 | 3 | 0 | **9%** | ✗ | First coral bleaching batch (9 drafts). Template convergence: 8 of 9 coral drafts share identical 2-sentence structure; 4 use near-verbatim DHW-persistence formula as second sentence. Costa Rica Pacific (A-): "heat that builds has nowhere to drain" — best closer since Apr 26 Mali. Galapagos (B+, score 88): strongest signal but conditional closer costs the A-. P3 self-kills and P4 Wodehouse violations both absent (fixes holding). Triage ON (PR #134, 2026-05-17) — sub-threshold coral drafts (7.2, 4.4°C-weeks) in this queue predate triage; expect fewer in next cycle. New proposals: coral bleaching template convergence (P6) + DHW formula over-deployment (P7). Staleness: 4 fire drafts flagged (BC explicit "today" + 3 fire "is radiating" >5 days); bulk-reject skipped — `gh` CLI unavailable; operator must use dashboard. |
| 2026-05-19 | 14 | 3 | 6 | 5 | 0 | **21%** | ✗ | First graded coral_bleaching batch (9 drafts). 3 A-: Madagascar (DHW contrast-reveal "persistence is what kills"), Galapagos (upwelling-failure + double mortality threshold), Costa Rica Pacific (no-upwelling "nowhere to drain"). 4 B+: Fiji/Nauru/Austral Islands coral + Siberia fire (P6 template broken; timing incongruity embedded). 2 B-: Bethel ME monthly_low + Stahl Peak snow extreme (5× record understated). 5 C/C+: 2 sub-threshold coral + Southern Borneo (low floor threshold) + Nooksack (station artifact "Mf Nooksack") + BC fire (stale). New proposals: P7 coral opener formula convergence, P8 snow ratio as punchline. P5 partially confirmed (fire drafts lack named mechanics). |
| 2026-05-20 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 18 carry-overs from May 12–18, all previously graded. Draft [18] (Siberia fire "today") newly crosses 48h staleness threshold (~69h). 5 fire drafts total await operator rejection (Drafts 1, 2, 4, 6, 18). No new proposals; no active proposal evidence updates. Triage ON; no-draft cause unconfirmed (triage-cap/score-gate/writer-kill cascade possible — operator should check suppression ledger). |
| 2026-05-22 | 0 | — | — | — | — | **—** | ✗ | No fresh drafts. 18 carry-overs all graded in prior cycles (May 13–19). 5 stale fire drafts identified for bulk-reject (drafts 1/2/4/6 fire + draft 18 Siberia "today"); bulk-reject skipped — gh CLI absent (7th consecutive skip). Queue static since May 15; 7 days without new drafts reaching pending. Likely cause: seasonal quiet or triage stage filtering; check `triage_cap` suppression ledger and `source_health`. No proposal evidence updates. |
| 2026-05-23 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 13 carry-overs (down from 18 — operator rejected 5 stale fire drafts on 2026-05-22 per BRIEFING.md: Mali + Campeche + Mongolia fire + BC fire + Siberia fire). 0 new staleness candidates; all 13 remaining drafts lack real-time-baked language. 4th consecutive no-fresh-draft grading cycle. Queue static since 2026-05-18T15:52Z. Routine beacon write attempted under new 0.9.1.0 Step 9.5 prompt. Proposals re-ordered by leverage (P5 > P7 > P8 > P_new). No proposal evidence updates. |
| 2026-05-24 | 0 | — | — | — | — | **—** | — | No fresh drafts. 13 carry-overs (same queue as May 23; no new operator actions). 0 bulk-reject candidates by policy; gh CLI absent (8th consecutive skip). Queue static since May 18T18:06Z. Most likely new suppression bottleneck: evidence contract gate (0.9.0.0) — operator should check `stage="evidence_contract"` suppression ledger for May 18–24. No proposal evidence updates. |
| 2026-05-25 | 0 | — | — | — | — | **—** | — | No fresh drafts. 13 carry-overs (same 13 as May 24). 5th consecutive no-fresh-draft cycle. Queue static since 2026-05-18T15:52Z (7 days, ~42 cron cycles). Evidence contract gate (`stage="evidence_contract"`, 0.9.0.0) remains the most likely suppression bottleneck — operator should verify kill count in suppression ledger before concluding signal drought. Coral drafts 7–10 days old; NOAA CRW DHW updated daily; operator must verify freshness before publishing. `gh` CLI absent (9th consecutive staleness-skip, May 13→May 25). No proposal evidence updates. |
| 2026-05-26 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 13 carry-overs (same queue as May 25). **6th consecutive no-fresh-draft cycle**; queue static since May 18T15:52Z (8 days, ~48 cron cycles). No bulk-reject candidates by policy; `gh` CLI absent (10th consecutive skip). Coral drafts now 8–11 days old; operator must verify NOAA CRW DHW values before publishing. Evidence contract gate most likely suppression bottleneck — operator should check `evidence_contract` kill counts in suppression ledger for May 22–26. No proposal evidence updates. |
| 2026-06-07 | 1 | 0 | 1 | 0 | 0 | **0%** | ✗ | First fresh draft in 19 days. Barrow, Alaska precipitation_extreme (213.8 mm/3d, 42.5% above record): B+ (permafrost drainage ecosystem specificity; "sheets across the surface instead" — implied contrast, soft close vs. A-grade declaratives). Restate-math minor violation (63.8 mm above the record of 150.0 mm). n=1; not statistically meaningful. 0.9.15.0 gpm S3 feed appears to have unlocked precipitation_extreme type. TTL sweep cleared 13 carry-overs including 3 A-/B+ coral drafts. P5 not observed (ecosystem specificity deployed naturally). |
| 2026-06-08 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 1 carry-over (Barrow Alaska precipitation_extreme, B+ from Jun 7 — not re-graded). Queue static since Jun 7T04:07Z (~35h). No proposal evidence updates. Staleness check: draft ~35h old, no real-time-baked language — clear. |
| 2026-06-09 | 0 | — | — | — | — | **—** | — | No fresh drafts. Queue now empty (0 pending; Barrow AK precipitation_extreme draft cleared between Jun 8 ~15:00 UTC and Jun 9 ~15:00 UTC — likely published or operator-rejected). No proposal evidence updates. P_new (cold record quality floor) moved to Resolved: 6 consecutive fresh-draft cycles without observation (May 15–19 + Jun 7). `gh` CLI absent (13th consecutive staleness skip). |
| 2026-06-10 | 0 | — | — | — | — | **—** | — | No fresh drafts. Queue confirmed empty (0 pending; verified Jun 9 clear still holds). No proposal evidence updates. P_new archived in Jun 9 run; P5/P7/P8 at last-known counts. Pipeline healthy (0.9.22.0+). `gh` CLI absent (14th consecutive staleness skip). |
| 2026-06-11 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. Queue confirmed empty (3rd consecutive no-fresh-draft cycle since Jun 7). Barrow Alaska B+ carry-over cleared between Jun 8–9 by operator (under 7d TTL, not auto-expired; likely published). No new drafts since Jun 7T04:07Z (4 days). No proposal evidence updates; P_new archived Jun 9. `gh` CLI absent (15th consecutive staleness skip). |
| 2026-06-12 | 0 | — | — | — | — | **N/A** | — | No pending drafts. Jun 7 Barrow draft confirmed posted. 1 approved draft (Chesnee SC monthly_low, Jun 10, score 86) graded B+ as voice observation (not pending). Same B+/A- implied-close gap as Barrow Jun 7: "threaten gardens well into early summer" implies frost vs. declarative form. New proposal P_close added. P_new not triggered — Chesnee counter-evidence (35yr archive, 7°F margin, SE US — fails all kill criteria). Bot at 0.9.47.0 (voice engine unchanged). `gh` CLI absent (16th consecutive staleness skip). |
| 2026-06-13 | 2 | 0 | 0 | 2 | 0 | **0%** | ✗ | 2 fresh drafts: monthly_low (Red Dog Mine AK — P_new re-activated, 17yr/1°F/Arctic Circle, C+); dust_event debut (Riyadh — 2,083 μg/m³ flat without WHO ref, C). P_close 3rd cycle (Red Dog Mine: mechanism-only close — most concrete evidence yet). P_dust new proposal added. Supply flags WRITER_SAMPLES=2+CRITIC_REVISE now live. No Wodehouse violations. Bot at 0.9.67.0. |
| 2026-06-14 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 2 carry-overs from Jun 13 (Red Dog Mine C+, Riyadh C — not re-graded). Both ~31h old; neither stale by policy. No proposal evidence updates. P_close/P_new/P_dust unchanged from Jun 13 counts. |
| 2026-06-15 | 9 retro | 6 | 2 | 1 | 0 | **67%** | ✓ | Retroactive grades: 9 drafts posted/approved/rejected Jun 2–15; 0 pending. **First cycle above 50% bar (retroactive caveat).** Suppression-failure + ecosystem isolation mechanics driving A-range. P_new confirmed (Red Dog Mine rejected — 17yr, 1°F, Arctic; 2nd cycle). P7 counter-evidence (2 coral drafts used alt opener forms → Resolved). New types: hot10 (B+), dust_event (B). Chesnee SC (approved Jun 10) missing posted_at — possible posting failure. |
| 2026-06-16 | 0 | — | — | — | — | **N/A** | — | 0 pending drafts. No new evidence for any active proposal. Pipeline active (triage_cap + critic + writer + fact_check kills observed in Jun 15 22:27 suppression log). Chesnee SC posting flag from Jun 15 unresolved — operator verify. 20th consecutive staleness-skip. |
| 2026-06-17 | 1 | 0 | 1 | 0 | 0 | **0%** | ✗ | 1 new draft: Urumqi China dust_event (B- — "traps it" declarative close vs Riyadh's "disperses it"; better close, same WHO-calibration gap). 4 of 5 gist drafts since Jun 8 already graded in Jun 12–15 entries (Chesnee A-, Beaver Dams A-, Riyadh C/B, Red Dog Mine C+). P_dust 2nd cycle confirmed (Urumqi: 2,260 μg/m³ = 151× WHO PM2.5 daily; unstated). P8 retired (4 fresh-draft cycles without snow_extreme since May 19). 21st consecutive staleness skip. |
| 2026-06-18 | 2 | 0 | 2 | 0 | 0 | **0%** | ✗ | 2 fresh precipitation_extreme drafts. Barrow AK (71.2 mm single-day, prior record 0.0 mm — B+): elite signal, over-packed sentence 2, P_close implied close ("any of it"). Amsterdam (314.4 mm / 7d, 4.8% above prior — B): thin margin, restate-math, P_close implied close ("stack up faster than they drain"). Opener template convergence across all 3 precipitation_extreme corpus drafts → P9 added. P_close 5th cycle. 22nd consecutive staleness skip. n=2. |
| 2026-06-19 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. Queue empty. All 3 Jun 18 precipitation_extreme drafts operator-rejected (Barrow daily B+, Amsterdam B, Barrow 7-day [ungraded, created Jun 18T15:43Z after prior grading window]). First operator rejection of a B+ graded draft (Barrow 71.2mm/prior 0.0mm). No proposal evidence updates. 23rd consecutive staleness skip. |
| 2026-06-22 | 1 retro | 1 | 0 | 0 | 0 | **100%** | (n=1) | Retroactive grade: Barrow 7-day precip (A-) — flagged ungraded in Jun 19/21. "Has nowhere to go" = first precipitation_extreme declarative-consequence close (P_close positive evidence). Restate-math confirmed (P9 3rd cycle). Queue empty (4th consecutive day). 25th staleness skip. |
| 2026-06-23 | 3 | 1 | 2 | 0 | 0 | **33%** | ✗ | 3 fresh drafts (created Jun 22T17–19Z, after prior grading window). Cope Rch TX all_time_high (A-): "push extremes fast" = declarative-consequence, P_close positive evidence; accelerating-warming + ecosystem specificity. Columbus GA all_time_high (B): 1°F margin, dual-mechanism second sentence, P_close 6th cycle failing. Mediterranean SST regional_sst_anomaly (B): comparative-implied close ("retains heat faster than open-ocean basins"), "today" staleness risk at Jun 24T17:12Z, unexplained NOAA 2.5°C threshold (A3 filed). 26th consecutive staleness skip. |
| 2026-06-24 | 2 | 0 | 2 | 0 | 0 | **0%** | ✗ | 2 fresh drafts. Randolph UT monthly_high B+ (134yr archive, ecosystem specificity "normally blunts" — P_close 7th cycle failing, implied-consequence form). Al Aḥmadī Kuwait air_quality_hazard B (10.1× WHO stated, shamal mechanism — P_close 7th cycle failing, resolution-close subtype "by evening"; P_dust positive: WHO ratio present unlike dust_event drafts). First air_quality_hazard in corpus. Draft [2] "June 24" date-baked — stale by Jun 26T14:50. 27th consecutive staleness skip. |
| 2026-06-25 | 5 | 0 | 4 | 1 | 0 | **0%** | ✗ | 5 fresh drafts. Siberia fire B+ (965.6 MW, highest in corpus; companion-fire peer comparison + "burns deep" = P_close positive). Barrow precip B+ (ratio-to-annual-precip P_close positive; P9 template 5th). Michigan monthly_low B (lake-effect, P_close failing). Taiz Yemen dust_event ×2 (C+/B-): P_dust 3rd cycle, all 4 dust_event corpus drafts template-converged. P_close 8th cycle: 3 failing, 2 positive. 28th consecutive staleness skip. |
| 2026-06-26 | 3 | 0 | 1 | 2 | 0 | **0%** | ✗ | 3 fresh drafts (all precipitation_extreme). Anchorage B (183.8 mm/3d, 22.5% margin, orographic stall mechanism, P_close mechanism-only failing). Amsterdam C+ (157.1 mm, 4.73% margin, canal-capacity incongruity, P_close implied-consequence failing). Aktobe C+ (150.8 mm, 0.53% margin, steppe-aridity + half-year ratio, P_close borderline). Threshold artifact: all 3 cite "previous 3-day record of 150.0 mm" — detection threshold used as prior record (`previous_record_year: null`). P9 6th cycle: all 3 use opener template; all 3 have restate-math. P_close 9th cycle: Anchorage mechanism-only + Amsterdam implied-consequence failing; Aktobe half-year ratio borderline. 29th consecutive staleness skip. |
| 2026-06-21 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. Queue empty (~2.5d since last resolved drafts Jun 18). P_new archived (2nd time) — 3 consecutive cycles without cold-record: Jun 15/17/18. No evidence updates for P_close/P9/P_dust/P5. 24th consecutive staleness skip. |
| 2026-06-27 | 2 | 0 | 1 | 1 | 0 | **0%** | ✗ | Fire + precipitation_extreme. Fire (Canadian Prairies/BC, 1,517.9–2,979.4 MW): B+ — comic triple, three-fire national cluster, period-form closer; BC fires at ~3,000 MW undersold by minimum-threshold framing in S3. Precipitation (Amsterdam, 157.1 mm, 4.7% above record): C+ — ecosystem specificity correct, signal too thin (score 74, 7.1 mm margin, maritime climate). P6 fire formula fix holding (3rd post-ship fire draft). P5 natural mechanic deployment 2nd consecutive cycle (comic triple + ecosystem specificity deployed without explicit naming). P_precip_floor new proposal: writer over-passes shallow-margin precipitation records in wet-climate locations. n=2, not statistically meaningful. 13th consecutive gh staleness skip. |
| 2026-06-29 | 5 | 4 | 1 | 0 | 0 | **80%** | ✓ | 5 fresh (1 Jun-28 carry-over not re-graded). [2] marine_heatwave A- (floor/ceiling inversion; "already the floor of a new streak" — first marine_heatwave in corpus). [4] Congo fire A- (first A-grade fire in two-bot corpus; ecosystem incongruity "convective lid"). [5] Prudhoe Bay A- (91°F at 70°N; latitude peer-comparison; P_compound 2nd cycle). [6] Amsterdam A- (declarative close "nowhere for the water to go"; P9 8th cycle; P_precip_floor 2nd cycle). [3] France reganom B+ (pre-#349; P_close failing). P_close 11th cycle: 3 pos/1 fail/1 n/a. **BAR CLEARED: 80% > 50% resumption bar.** 31st consecutive staleness skip. Immediate operator attention: [1] Mediterranean stale ~Jun 30T04Z, [2] marine_heatwave stale ~Jun 30T17Z. |
| 2026-06-28 | 5 | 0 | 4 | 1 | 0 | **0%** | ✗ | 5 fresh (2 Jun-27 carry-overs not re-graded). [3] Taiz dust_event C+ (P_dust 4th cycle, no WHO anchor, mechanism-only P_close fail; 5th consecutive dust_event template-converged). [4] Mediterranean SST B+ (P_close borderline positive "nowhere fast to go" — closest to declarative in batch). [5] Astana precip B+ (51.1/3.9 mm = 13× implicit; steppe closer; P9 7th cycle). [6] Beaver Dams all_time_high B+ (P_close implied fail; P_compound new — archive+margin double-qualifier). [7] Casper monthly_low B (P_close implied fail; P_compound 2nd obs). P_close 10th cycle. New proposal P_compound. No Wodehouse violations (7th consecutive clean cycle). 30th consecutive staleness skip. |
| 2026-06-30 | 9 | 2 | 5 | 2 | 0 | **22%** | ✗ | 10 pending (1 stale excl.: Mediterranean regional_sst_anomaly "today" ~59h). 2 A-: GMST marine_heatwave (floor/ceiling inversion "already the floor of a new streak" — first marine_heatwave graded this cycle); Prudhoe Bay all_time_high (92 score, 101°F at 70°N, latitude peer-comparison). 5 B: France reganom B+, Astana B+, Antwerpen B+, Amsterdam B, Colorado B-. 2 C+: Phalodi + Taiz dust_event (P_dust 5th+6th cycle, zero named mechanics, WHO anchor absent). P9 9th cycle: 3/3 fresh precip drafts (Astana/Antwerpen/Colorado) show opener template + restate-math. P5: dust_event still no named mechanics (2nd consecutive cycle). regional_anomaly debut: France reganom B+ (score 88, 6-city +8.4°C avg, 2.8σ — first reganom in corpus post-#349). A-rate: 22% (below bar cleared Jun 29; different signal mix, fewer A-prone types). 32nd consecutive staleness skip. |
| 2026-07-01 | 4 | 0 | 3 | 1 | 0 | **0%** | ✗ | 14 pending (10 carry-overs from Jun 28–30, unchanged; 4 fresh). Basrah, Iraq absolute_extreme B (83 score, "offers no evaporative relief" P_close positive, but sentence 1 names its own internal tier — "the 47°C absolute-extreme threshold for the Northern Subtropical band"). Morrill Fire, Nebraska fire_footprint B (first of type; "the underlying sand can begin to shift" is the batch's best closer; same tier-jargon cap — "the 250,000-hectare tier that marks a continent-scale footprint"). Al Baṣrah al Qadīmah, Iraq absolute_extreme B- (same Basra metro area as the Jun-30 draft, 3 days later; same tier-jargon; softer mechanism-only close). Wadi Halfa, Sudan dust_event C+ (8th consecutive dust_event draft, still no WHO/consequence anchor; two-step lift/settle mechanism is the best-constructed dust mechanism yet). **New pattern promoted to active proposal P_tier** (was A3, awaiting-evidence since Jun 23): 4 of 14 pending drafts across 3 signal types state an internal scoring-tier name verbatim instead of describing the world. 2 stale carry-overs newly flagged: [1] Mediterranean SST (~83h, "today") and [2] GMST marine_heatwave (~70h, "today's reading") — both bulk-reject candidates, `gh` unavailable. **Operational note:** `main`'s copies of these docs are stale since Jun 8; this cycle continues grading on the unmerged `daily-plan-current` rolling branch, which carries 23 days of cycles (Jun 9–Jun 30) main doesn't have yet. 33rd consecutive staleness skip. |
| 2026-07-02 | 3 | 0 | 2 | 1 | 0 | **0%** | ✗ | 17 pending (14 carry-overs from Jun 28–Jul 1, unchanged; 3 fresh). Ft Green, Florida all_time_high B ×2 (102°F, 26yr archive, 1°F margin — P_compound double-qualifier; same reading + margin on consecutive days, likely duplicate-location cluster; first draft "the lid lifts fast" B, second reused weaker "overcome that convective ceiling" close C+). Basrah, Iraq absolute_extreme B (48°C, 3rd Basra-area draft in 3 days; P_tier tier-jargon leak — "threshold marking absolute extremes for this latitude band" — same cap as Jul 1's two Basra drafts). P_tier 4th cycle / 6th instance. P_compound 4th cycle. P_close 13th cycle (1 positive, 1 failing, 1 borderline). No dust_event/precipitation_extreme drafts this cycle — P9/P_dust/P5 no new evidence; P_precip_floor archived (3 consecutive cycles without a qualifying observation). 2 carry-overs still stale and unactioned: Mediterranean SST (3rd cycle) and GMST marine_heatwave (2nd cycle). New: all 3 `absolute_extreme` corpus drafts ([11]/[13]/[16]) now have forecast dates that have elapsed by grading time — none crosses the mechanical 48h threshold but all misstate the date if posted. 34th consecutive staleness skip. |
| 2026-07-03 | 3 | 1 | 1 | 1 | 0 | **33%** | ✗ | 20 pending (17 carry-overs from Jun 28–Jul 2, unchanged; 3 fresh). Canadian Arctic fire A- (792 MW, "reaches carbon the frozen ground has held for millennia" — 3rd P_close-positive carbon-release fire close after Jun 25 Siberia, strongest yet). Near-duplicate Canadian Arctic fire B+ (same 792 MW signal, drafted 68 seconds after the first, weaker "centuries"/"organic soil layers" close). Typhoon Bavi C+ (first `cyclone_rapid_intensification` in corpus; "the rapid-intensification threshold is 30 kt in 24 hours" — P_tier's 4th signal type; ratio-as-punchline close undercut by sharing its clause with the tier-jargon leak; raw JTWC URL appended to the tweet text — likely bundle-leak bug, flagged for the engineer, not folded into the grade). P_close 14th cycle (2 positive). P_tier 5th cycle / 7th instance / 4th signal type. Duplicate-generation pattern now confirmed a 3rd time across a 3rd signal type (Ft Green all_time_high, Basrah absolute_extreme, now Canadian Arctic fire). 3 carry-overs newly/still stale: Mediterranean SST (4th cycle), GMST marine_heatwave (3rd cycle), and [11]/[13] Basra-area absolute_extreme both newly cross the 48h mechanical threshold on top of their already-elapsed forecast dates. 35th consecutive staleness skip. **Operational note: `main` still unmerged since Jun 8 — 25 consecutive daily cycles stranded on `daily-plan-current`, including the Jun 29 bar-clearing (80%) cycle.** |
| 2026-07-04 | 10 | 2 | 4 | 0 | 0 | **20%** | ✗ | **Complete queue turnover** — all 20 of Jul 3's pending drafts (including the 4 stale reject-candidates) are gone; 10 fresh drafts, zero carry-overs; cause unconfirmed (bulk-reject/publish/TTL — operator should verify). Largest statistically-meaningful sample since Jun 29 (n=5). 2 A-: Typhoon Bavi (2nd `cyclone_rapid_intensification` draft — avoids the P_tier violation that capped Jul 3's 1st instance at C+, lands the type's first P_close-positive close: "storms... can intensify faster than forecasters or ships can react"); Loxahatchee FL all_time_high ("the column runs free" overcomes a P_compound double-qualifier opener). 2 B+: Island Pond VT all_time_high (P_compound, P_close failing/hedged); Antwerpen precip — **value-identical re-issue of the Jun 30 B+ draft under a new draft_id**, graded on precedent not fresh evidence. 6 B: Barrow + Astana precip (**P9 reopened** — both repeat the archived opener-template + restate-math pattern on the very first reappearance, exactly as the Jul 3 archive note predicted; Astana's close is P_close FAILING at a new low — a bare fact with no mechanism or consequence, stranding the batch's best joke: 358mm/week vs ~300mm/year); Basrah + Al Başrah al Qadīmah absolute_extreme (4th/5th Basra-area instances, both repeat the P_tier tier-jargon leak, P_tier caps at B regardless of P_close quality — consistent with [11]/[16] precedent); Rocky Mountains CO fire (mid-latitude drought-mechanism-only class, same as Jun 30's Colorado B-, graded B on slightly better ecosystem specificity); Urumqi dust_event (P_dust confirmed again, no WHO anchor). P_close 15th cycle (3 positive, 6 failing). P_tier 6th cycle / 9 instances / still 4 signal types. P_compound 5th cycle. P9 reopened after 1 cycle archived. `gh` CLI absent, 36th consecutive skip. |
| 2026-07-05 | 5 | 1 | 3 | 1 | 0 | **20%** | ✗ | 15 pending (10 carry-overs from Jul 4, unchanged; 5 fresh). 1 A-: eastern Siberia fire (556.1 MW; "doesn't just burn the surface — it thaws the ground beneath it" — 4th corpus confirmation that the permafrost-carbon fire mechanic reliably clears P_close, joining Jun 25 Siberia and Jul 3 Canadian Arctic ×2). 1 B+: Johannesburg air_quality_hazard (10.9× WHO stated, richer causal chain than Jun 24's Al Aḥmadī — "Highveld winter" + household-burning source attribution — but P_close failing, accumulation-not-consequence close). 1 B: Doha, Qatar absolute_extreme — **P_tier confirmed outside the Basra-area cluster for the first time** (same tier-jargon phrase on a city 1,500+ km from Basrah), P_close positive (best close of the signal type yet — "closing off the evaporative cooling that makes extreme dry heat survivable") but still capped at B, reconfirming P_tier is a hard ceiling regardless of close quality. 1 B-: 3rd Urumqi dust_event draft — same station, 3rd distinct reading, near-verbatim repeat of the same resolution-form close for a 3rd time (new duplicate-location subtype: frozen mechanism, varying reading). 1 C+: Phalodi, India dust_event (10th dust_event corpus draft, no WHO anchor, resolution-form close, no named mechanic). P_close 16th cycle (2 positive, 3 failing). P_tier 7th cycle / 10 instances / 1st cross-location confirmation. P_dust 9th cycle (11 of 11 dust_event instances without WHO anchor). P9/P_compound not tested this cycle (no precipitation_extreme or record-type draft). `gh` CLI absent, 37th consecutive skip. **Operational note: `main` still unmerged since Jun 8 — 28 consecutive daily cycles stranded on `daily-plan-current`.** |
| 2026-07-06 | 0 | — | — | — | — | **N/A** | — | No fresh drafts — queue is an exact match to Jul 5's 15 graded drafts (same `draft_id`s, scores, text); no re-grading performed, all grades stand. No active-proposal evidence updates (P_close/P_tier/P_dust/P9/P_compound/P5 all unchanged from Jul 5). **2 strict staleness bulk-reject candidates newly identified:** [4] Basrah and [6] Al Başrah al Qadīmah `absolute_extreme`, both >48h old (56.2h/52.8h) with a forecast date (July 4) now 2 days elapsed — same Basra-area class flagged Jul 1–3. Write skipped: `gh` CLI absent, no gist-write tool available via the GitHub MCP server this session (38th consecutive skip, May 13 → Jul 6) — logged for operator manual reject. [15] Doha's forecast date (July 5) has also elapsed but is under 48h — flagged to watch, not yet a strict candidate. **Operational note: `main` still unmerged since Jun 8 — 29 consecutive daily cycles stranded on `daily-plan-current`, including the Jun 29 bar-clearing (80%) cycle.** |
| 2026-07-07 | 6 | 2 | 4 | 0 | 0 | **33%** | ✗ | **Complete queue turnover (2nd occurrence)** — all 15 Jul-6 drafts gone (incl. the 2 unactionable Basra-class staleness candidates), 6 fresh drafts, all created same-day. **Major overnight pipeline push:** `main` merged (#384) — the 29-cycle unmerged saga is over; P_tier + P_dust SHIPPED as code (#386, "detection-plumbing ban + dust PM10 WHO anchor," merged 05:06:48Z); Basra-class staleness got a structural pipeline fix (#385, forecast-elapsed auto-reject, merged 04:55:15Z) — likely explains the turnover. 2 A-: Snowshoe, WV all_time_high (P_compound present but overcome — "89°F is the kind of reading the valley floor expects, not the ridge," declarative elevation-inversion); Soweto, South Africa air_quality_hazard (**first A- for this signal type** — "nowhere to vent," WHO 10.3×). 3 B: Ahvaz, Iran absolute_extreme (pre-fix, P_tier violation caps a strong "no relief from elevation or sea" close); Aibonito, Puerto Rico `record` (**new signal type debut** — day-of-year record, mechanism-only/expository close, P_close 15th confirmed type); Riyadh, Saudi Arabia air_quality_hazard (post-fix, but "This is a PM2.5 signal, not dust" is a fresh self-reference variant — new proposal **A4** filed). 1 B-: Zaragoza, Spain absolute_extreme (pre-fix, P_tier violation on a **new band name** "northern mid-latitudes," weak mechanism-only close). **Fix-timing straddle:** the 2 pre-fix absolute_extreme drafts (03:39/03:40 UTC) show the violation exactly as expected; the 4 post-fix drafts (07:44–14:56 UTC) are all non-targeted types, so neither fix is empirically confirmed yet — first real test awaits the next `absolute_extreme`/`fire_footprint`/`cyclone_rapid_intensification`/`regional_sst_anomaly` draft (P_tier) or `dust_event` draft (P_dust). P_close 17th cycle (3 positive: Snowshoe, Soweto, Ahvaz; 3 failing: Zaragoza, Aibonito, Riyadh). P_compound 6th cycle (Snowshoe). `air_quality_hazard` self-selects for a 4th consecutive cycle. 39th consecutive `gh` staleness skip (0 candidates — all same-day fresh). |
| 2026-07-08 | 8 | 4 | 4 | 0 | 0 | **50%** | ✗ | **Complete queue turnover (3rd occurrence)** — all 6 Jul-7 drafts gone, 8 fresh drafts, all created same-day, all safely post-fix for every item shipped since Jul 5 (P_tier/P_dust via #386, precip four-moves/P9 via #397, cyclone four-moves via #404). Closest approach to the bar since Jun 29's 80% clearance; 50% is exactly half, not a majority, so the bar is technically not cleared. 4 A-: Barrow AK precip (71.2mm/day, prior record 0.0mm, "one storm just delivered two-thirds of a normal year in a day" — first fully clean precipitation_extreme draft in corpus history); Astana precip (51.1mm, "roughly a sixth of a typical year's rain," same clean form); Anchorage precip (370.4mm/7d, ratio-anchor leads sentence 1, declarative orographic-compression close — best-constructed of the three); Riyadh air_quality_hazard (10× WHO, "basin-scale loading, not a street-corner spike" — new scale-honesty-contrast close subtype, A4 does not recur). 3 B+: Snowshoe WV all_time_high (P_compound 7th cycle; P_close FAILING — a materially weaker close than this same station's Jul 7 A- draft one day earlier); Typhoon Bavi `cyclone_landfall` (**new signal type**, P_close POSITIVE "sustain major typhoon strength almost to the coast," but a 2nd raw-JTWC-URL bundle-leak bug); Riyadh dust_event (**P_dust fix empirically confirmed for the first time** — 27.9× WHO PM10 stated, closing the 11-for-11 gap tracked since Jun 13; P_close still FAILING, mechanism-only, unaffected by the WHO-anchor fix). 1 B: Typhoon Bavi `cyclone_land_threat` (**new signal type**, the kind PR #388 added to close the "Bavi gap" — forecast-tense rules followed precisely, but P_close FAILING on a purely expository debut close, same as every other type's first appearance). P_close 18th cycle (5 positive, 3 failing; 16th/17th confirmed signal types via the two new cyclone kinds). P_compound 7th cycle. **P_dust and P9 empirically confirmed clean for the first time** (1 cycle each). P_tier not tested on a named target type this cycle. Operator notes: possible Bavi landfall/land_threat bundle-sequencing inconsistency (verify advisory timestamps before publishing both); 2nd raw-URL bundle leak (flag to engineer). 40th consecutive `gh` staleness skip (0 candidates — all same-day fresh). |
| 2026-07-09 | 2 | 1 | 1 | 0 | 0 | **50%** | ✗ | **Complete queue turnover (4th occurrence)** — all 8 Jul-8 drafts gone, 2 fresh drafts, both created same-day (03:26–03:29 UTC). n=2, so 50% is 1 draft, not a majority — 2nd consecutive cycle landing exactly on the half-boundary (after Jul 8's 4/8). 1 A-: Stevensville, Maryland all_time_high (103°F, "beating a record from 1934, by 2°F, in 101 years of data" — **worst P_compound instance yet**, a triple-stacked qualifier one past every prior double-qualifier instance; overcome by a clean buffer-failure declarative close, "that buffer failed," same shape as Jun 29's Congo fire A-). 1 B: Anchorage, Alaska precipitation_extreme (61.2mm/day against a 0.9mm prior record — exactly 68×, the corpus's most dramatic precip ratio, left unstated; P9-clean of restate-math and the legacy template, but P_close FAILING on "wring out moisture in concentrated bursts" — one word from Jun 26's own Anchorage draft, "wring out moisture in compressed bursts," and notably weaker than this same station's Jul 8 A- draft two days earlier). **P9 gets its 2nd independent clean cycle (Jul 8 3/3 + Jul 9 1/1) — tracking closes, see IMPROVEMENT_PLAN.md.** P_close 19th cycle (1 positive, 1 failing). P_compound 8th cycle (new worst instance). P_tier/P_dust/A4/A5 not tested (no target-type draft). 41st consecutive `gh` staleness skip (0 candidates — both same-day fresh). |
| 2026-07-10 | 3 | 1 | 2 | 0 | 0 | **33%** | ✗ | **Complete-turnover streak breaks** — 2 of Jul 9's 2 drafts survive as carry-overs (Stevensville A-, Anchorage B, unchanged), first non-full-turnover cycle since Jul 6. 3 fresh: 1 A-, Ahvaz, Iran absolute_extreme (47.1°C forecast — **first post-fix P_tier confirmation on a named target type**, no band-label jargon this time vs. this same city's Jul 7 pre-fix "absolute-extreme threshold for the Northern Subtropics"; declarative close "where shade and rest alone stop being enough" — first A-grade `absolute_extreme` draft in the corpus). 2 B+: Riyadh dust_event (24.9× WHO stated — **2nd post-fix P_dust confirmation, tracking closes** on the same 2-clean-cycles bar P9 used; close still structural not declarative); Tepee Creek, MT all_time_high (standard P_compound double-qualifier + implied P_close, same combination that's produced B/B+ throughout this proposal). P_close 20th cycle. P_tier: 1st post-fix confirmation (parallels P_dust's Jul 8 milestone — watch for a 2nd before moving to Resolved). P_dust: 2nd post-fix confirmation, tracking closes. P_compound 9th cycle. A4/A5 not tested (no air_quality_hazard/cyclone_land_threat draft). 0 staleness candidates (oldest carry-over ~35.7h); `gh` CLI absent, 42nd consecutive skip. |
| 2026-07-11 | 2 | 0 | 2 | 0 | 0 | **0%** | ✗ | 6 pending (4 carry-overs from Jul 9/10 unchanged: Stevensville A-, Riyadh dust_event B+, Tepee Creek B+, Ahvaz A-; 2 fresh, both `fire`). Anchorage precipitation_extreme (B) drops from the queue — cause unconfirmed. 2 B+: interior Alaska fire (926.3 MW, 66°N, "doesn't just consume trees — it burns into the organic layer above the frozen ground" — 6th permafrost-carbon-mechanic instance, P_close positive-but-weak, same tier as Jul 3's near-dup); western Siberia fire, a 3-signal comic-triple cluster (1,387.9/958.0/720.7 MW, "burning across peat that took centuries to accumulate" — same declarative-but-weak P_close form). **New: A6 filed** — both closes independently reuse a prior corpus draft's exact phrasing on a different fire event (Alaska echoes Jul 5 eastern Siberia's "doesn't just X — it Y" construction; Siberia echoes Jul 3's near-dup "...that took centuries to accumulate" clause) — the permafrost-carbon mechanic, this plan's most reliable fire A-grade path, shows its first sign of curdling into a reused phrase bank across different events, not just the already-tracked within-location duplicate-generation anomaly. P_close 21st cycle (2 positive, both weak-declarative form). P5: fire self-selects again (5th/6th consecutive confirming cycle). P_tier/P_dust/P9/P_compound/A4/A5 not tested (no target-type draft this cycle). 0 staleness candidates (Stevensville/Riyadh past-tense carve-out regardless of age; Tepee Creek/Ahvaz/fires all <29h); `gh` CLI absent, 43rd consecutive skip. Operator note: Ahvaz's forecast date (July 10) elapsed but sits under 48h — worth confirming whether PR #385's forecast-elapsed auto-reject is age-gated by design. |
| 2026-07-12 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. 5 pending — exact match to 5 of Jul 11's 6 graded drafts (Stevensville A-, Riyadh dust_event B+, Tepee Creek B+, interior Alaska fire B+, western Siberia fire cluster B+); no re-grading performed, all grades stand. **Ahvaz, Iran `absolute_extreme` (A-) drops from the queue** — cause unconfirmed, 2nd consecutive cycle of unexplained single-draft contraction (after Anchorage's Jul 10→11 departure). Losing Ahvaz costs the corpus its best open P_tier test case (it was 1 of 2 confirmations needed to close that proposal's tracking); its Jul 10 grade record is unaffected, but closing P_tier now needs a fresh target-type draft. No active-proposal evidence updates (P_close/P_compound/P5/P_tier/P_dust/P9/A4/A5/A6 all unchanged from Jul 11). 0 staleness candidates (Stevensville/Riyadh/Tepee Creek past-tense carve-out; both fires <33h, western Siberia's "today" still under the 48h line, watch ~2026-07-13T06:25Z). `gh` CLI absent, 44th consecutive skip. |
| 2026-07-13 | 0 | — | — | — | — | **N/A** | — | No fresh drafts — queue is an exact match to Jul 12's 5 graded drafts (same `draft_id`s, scores, text); no re-grading performed, all grades stand. No active-proposal evidence updates (P_close/P_compound/P5/P_tier/P_dust/P9/A4/A5/A6 all unchanged from Jul 12). **1 strict staleness bulk-reject candidate newly identified:** western Siberia fire cluster, now ~56.6h old with "today" still in the text — crosses exactly the threshold flagged proactively in the Jul 11 and Jul 12 entries. Write skipped: `gh` CLI absent, no gist-write tool available via the GitHub MCP server this session (45th consecutive skip, May 13 → Jul 13) — logged for operator manual reject. Interior Alaska fire (same ~56.6h age, no date/time language) and the three past-tense record drafts (Stevensville/Riyadh/Tepee Creek) remain clear under the established carve-out. **Docs-freshness note:** `main`'s copies of these three docs were still at their Jul 6 state at session start (the #384 merge was a one-time snapshot, not a standing sync) — confirmed the rolling `daily-plan-current` branch itself has run every day since with no gap (Jul 7–12 all present); rebased this session's work onto fresh `main` cleanly, no re-grading performed. |
| 2026-07-14 | 3 | 1 | 1 | 1 | 0 | **33%** | ✗ | 8 pending (5 carry-overs from Jul 9–11, unchanged; 3 fresh). **Headline: P_tier's tracking closes.** 1 A-: Basrah, Iraq absolute_extreme ("3°C above the 47°C threshold where the body's cooling mechanisms begin to fail faster than they can recover" — clean of band-label jargon, the **2nd independent post-fix confirmation** on a named target type after Jul 10's Ahvaz, closing P_tier's tracking on the same 2-clean-cycles bar P_dust/P9 used; declarative P_close "removes the ceiling"). 1 B+: Randolph, Utah all_time_high (134yr archive, standard P_compound double-qualifier, 10th cycle; P_close implied/failing — "normally bleeds off the heat" echoes this same city's own Jun 24 draft's "normally blunts the heat" near-verbatim, 20 days apart, different record type — new watch-item **A7** filed). 1 C+: Ontario, Canada fire cluster (2,374.8/883.7/817.1 MW — **P5 counter-instance**, breaks the fire category's 6-cycle self-selection streak; bare 3-signal-count restatement with zero ecosystem-specific mechanic, unlike this same cycle's western Siberia carry-over which proved cluster framing and a real mechanic are compatible). P_close 22nd cycle (1 positive, 1 failing). P_compound 10th cycle. **All three of this plan's shipped code fixes (P_tier, P_dust, P9) are now CONFIRMED.** 46th consecutive `gh` staleness skip — 1 strict candidate (western Siberia fire cluster, ~80.6h, "today" still present-tense, 2nd consecutive cycle unactioned). |
| 2026-07-15 | 0 | — | — | — | — | **N/A** | — | No fresh drafts. Queue **contracted from Jul 14's 8 to 6** — Randolph, Utah all_time_high (B+) and Ontario, Canada fire cluster (C+) both drop, cause unconfirmed (3rd/4th instance of this plan's recurring unexplained queue-contraction pattern, after Anchorage Jul 10→11 and Ahvaz Jul 11→12). Remaining 6 are an exact match to prior grading (Stevensville A-, Riyadh dust_event B+, Tepee Creek B+, interior Alaska fire B+, western Siberia fire cluster B+, Basrah absolute_extreme A-); no re-grading performed, all grades stand. No active-proposal evidence updates — P_close/P_compound/P5/A4/A5/A6/A7 all unchanged from Jul 14; P_tier/P_dust/P9 remain CONFIRMED, tracking closed. **Western Siberia fire cluster now unactioned for a 3rd consecutive cycle** (~104.7h old, "today" still present-tense). `gh` CLI absent, 47th consecutive skip. |
| 2026-07-16 | 2 | 2 | 0 | 0 | 0 | **100%** | ✓ (n=2) | 4 pending (2 carry-overs from Jul 11 unchanged: interior Alaska fire B+, western Siberia fire cluster B+; 2 fresh). **4 of Jul 15's 6 drop from the queue** (Stevensville A-, Riyadh dust_event B+, Tepee Creek B+, Basrah A-) — cause unconfirmed by gist inspection, but coincides with `bot.yml`'s posting/drafting/leaderboard schedules being stopped 2026-07-14 12:49 ET (`#441`) and restored 2026-07-15 22:46 ET (`#449`), which also explains Jul 15's zero-fresh-draft cycle and today being the first fresh drafts since the restore. 2 A-: Powderville, Montana all_time_high (score 91; 63yr archive, 4°F margin — P_compound double-qualifier present, 11th cycle, overcome by a clean named-absence declarative close, "no marine layer... no terrain to interrupt heat building," same family as Basrah's "no evaporative relief"); Oslo hot10 (score 87; +10.4°C July anomaly — peer/climate-analogy comparison + declarative accelerating-warming reframe, "is what a warmer baseline looks like at high latitudes," same interpretive-reframe shape as Jun 29's marine_heatwave A-; first `hot10` draft graded under this framework). **First 100%-of-cycle A-rate since Jun 22's retroactive n=1** — small-n, not durable confirmation, but the cleanest evidence yet that with P_tier/P_dust/P9 all shipped and confirmed (Jul 14), P_close and P_compound are the only two structural levers left between the pipeline and a sustained majority-A cycle. P_close 23rd cycle (2 positive, 0 failing). P_compound 11th cycle (1 instance, overcome). A4/A5/A6/A7 not tested (no target-type draft). **1 strict staleness bulk-reject candidate, 4th consecutive unactioned cycle:** western Siberia fire cluster (~128.7h, "today" still present-tense — the corpus's oldest unactioned candidate to date). `gh` CLI absent, 48th consecutive skip. |
| 2026-07-17 | 5 | 4 | 1 | 0 | 0 | **80%** | ✓ | 7 pending (2 carry-overs from Jul 11 unchanged: interior Alaska fire B+, western Siberia fire cluster B+; 5 fresh — largest batch since Jul 8's 8). 4 A-: Bandar-E Mahshahr, Iran absolute_extreme (score 84; "the air has nowhere to cool" — named-absence declarative, clean P_tier form); Deaver, Wyoming all_time_high (score 91, batch high; 111yr archive — longest in corpus — P_compound overcome by "the terrain that blocks moisture also traps heat"); Al Basrah, Iraq absolute_extreme (score 84; "one of the few places on earth where outdoor survival becomes genuinely contested" — batch's strongest declarative, single-sentence construction); Tunis hot10 (score 87; leaderboard-aggregate reframe — "heat this far from seasonal average has stopped arriving one city at a time," 1st cross-cohort close in the corpus, new candidate move). 1 B+: Basrah, Iraq absolute_extreme (score 84; **stranded mechanic** — the real declarative move, "shade and stillness stop being enough," is buried in sentence 1 instead of the closer; actual close is hedged/non-declarative, P_close FAILING; near-verbatim reuse of Jul 10 Ahvaz's "shade and rest alone stop being enough" — 2nd instance, new watch-item **A8** filed alongside a same-cycle 3-of-3 `absolute_extreme` opener-skeleton convergence). **First n≥5 bar-clearing cycle since Jun 29's 80%/n=5** — a materially stronger read than Jul 16's small-n 100%. P_close 24th cycle (4 positive, 1 failing). P_compound 12th cycle (1 instance, overcome). Zero Wodehouse violations, 2nd consecutive cycle. Likely duplicate-signal generation ([4]/[6], same metro area 8h apart) and a signal-mix monoculture (3 of 5 fresh `absolute_extreme`, all Persian Gulf/lower-Mesopotamian) logged as operational notes, not voice proposals. **Western Siberia fire cluster now unactioned for a 5th consecutive cycle, the corpus's longest-standing candidate** (~152.8h, "today" still present-tense). `gh` CLI absent, 49th consecutive skip. |
| 2026-07-18 | 4 | 1 | 3 | 0 | 0 | **25%** | ✗ | 7 pending (3 carry-overs from Jul 17 unchanged: Basrah absolute_extreme B+, Deaver all_time_high A-, Al Basrah absolute_extreme A-; 4 fresh). **Comedown from Jul 17's 80%, signal-mix driven** — zero fresh `absolute_extreme` this cycle (the type carrying 3 of Jul 17's 4 A-grades), drafts instead drawn from `precipitation_extreme` (2) and `air_quality_hazard` (1). 1 A-: Wausaukee, Wisconsin all_time_high (score 92; P_compound double-qualifier overcome by "without the lake bleeding it off first" — named-absence declarative). 2 B+: Delhi, India air_quality_hazard (score 74; WHO 10.8× stated, strongest `air_quality_hazard` device yet — monsoon expectation-reversal, "rains are supposed to wash the air... the seasonal scour isn't keeping up" — graded conservatively P_close FAILING per established precedent, though this grader flags it as a genuine judgment call that could be read as this type's first P_close-positive instance); Astana, Kazakhstan precipitation_extreme (score 76; lands the P9-era baseline-comparison move for the first time — companion-city triple [Aktobe/Almaty] + annual-baseline contrast, "three cities delivered a sixth of that at once" — but the arithmetic is ambiguous per-city vs. combined, capping it below A-). 1 B: Anchorage, Alaska precipitation_extreme (score 77; mechanism-only close, 51× ratio unstated, P_close FAILING). **Headline: A7 promoted to an active proposal** — Anchorage's close is the 3rd instance (Jun 26 → Jul 9 → Jul 18) of the same "moisture...compressed/concentrated...bursts" phrase family on one station, the 2nd location (after Randolph) confirming the "writer reuses its own prior closing construction" pattern past its Jul 14 promotion bar. P_close 25th cycle (1 positive, 1 conservatively-failing, 1 partial/ambiguous, 1 failing). P_compound 13th cycle (Wausaukee, overcome). Zero Wodehouse violations, 3rd consecutive cycle. **4 Jul-17 drafts dropped from the queue, cause unconfirmed** — Bandar-E Mahshahr A-, Tunis A-, interior Alaska fire B+, and notably the western Siberia fire cluster (the corpus's longest-standing staleness candidate, 5 consecutive unactioned cycles), plausibly operator action on the repeated reject recommendation. 0 strict staleness candidates; 2 watch items (Basrah ~37.0h, Al Basrah ~29.1h, both forecast-date-elapsed-but-under-48h — open question on whether PR #385's auto-reject should have caught these). `gh` CLI absent, 50th consecutive skip. |

**Trend interpretation:**
The Apr 25 jump to 43% was real but came from a small cohort (7 drafts) and didn't sustain into Apr 27. The Apr 27 regression has named causes (Sonnet rewrite path, verb-list gap in opener regex, era-anchor over-deployment, political anchor curation error). All four have proposed fixes documented in `docs/DRAFT_CORPUS.md` Apr 27 implications section. Next data point: tomorrow's scheduled grader (fires 2026-04-27 06:00 UTC) on the Apr 26-27 cycle output under v2.5 + post-humor-lens fixes.

We've been in the 9-43% band for three cycles. Need to clear 50% sustained.

## Rejection events

Drafts that got rejected, with dates.

### 2026-07-18 — Staleness bulk-reject: 0 strict candidates; 2 watch items; write skipped (50th consecutive skip)

**Status:** 7 pending drafts reviewed (4 fresh; 3 carry-overs from Jul 17). 0 strict candidates
(>48h old AND real-time-baked) — all 4 fresh drafts are same-day or 1-day-old (5.7h–21.9h). **2
watch items, both carry-over `absolute_extreme` drafts with elapsed forecast dates still under
the 48h mechanical threshold:** Basrah, Iraq (`draft_20260717_020203_127`, created
2026-07-17T02:02:03Z, ~37.0h old — "is forecast to hit 47.9°C (118°F) **today**," where "today"
meant July 17 at creation and is now a day stale) and Al Basrah, Iraq (`draft_20260717_095705_129`,
created 2026-07-17T09:57:05Z, ~29.1h old — "forecast to hit 48°C (118°F) **on July 17**," same
elapsed-date class). Neither crosses 48h yet — will if still pending tomorrow. Notable: PR #385's
forecast-elapsed auto-reject (shipped 2026-07-07) has not removed either draft roughly 12–15h past
their stated forecast date, an open question first raised Jul 11 about whether that mechanism is
age-gated by design or has a coverage gap for elapsed-but-under-48h drafts — flagged again for the
operator. **Separately (not a staleness rejection, logging for the record):** the western Siberia
fire cluster — Jul 13–17's strict bulk-reject candidate, unactioned for 5 consecutive cycles and
the corpus's longest-standing candidate — is gone from today's queue, along with 3 other Jul 17
drafts (Bandar-E Mahshahr, Tunis, interior Alaska fire). Plausibly the operator finally acting on
the repeated recommendation; cause is not observable from the gist alone, so not asserted as
confirmed. Write not attempted (0 qualifying candidates). `gh` CLI absent — 50th consecutive skip
(May 13 → Jul 18).

### 2026-07-17 — Staleness bulk-reject: 1 strict candidate identified (5th consecutive cycle unactioned, now the corpus's oldest); write skipped (49th consecutive skip)

**Status:** 7 pending drafts reviewed (5 fresh; 2 carry-overs from Jul 11). 1 strict bulk-reject
candidate, unchanged identity from the last four cycles: **western Siberia fire cluster**
(`draft_20260711_062452_120`, created 2026-07-11T06:24:52Z, ~152.8h old at grading — first
flagged Jul 13 at ~56.6h, now the 5th consecutive cycle unactioned, extending its own record as
the corpus's oldest unactioned strict candidate). Text still reads "Three fire signals in the
same patch of western Siberia **today**" — present-tense, real-time-baked, now describing a fire
event over 6 days stale. Interior Alaska fire (`draft_20260711_062334_119`, same ~152.8h age)
contains no date/time language — clear under the established carve-out, consistent with every
prior ruling on this draft since Jul 11 (6 consecutive cycles now). All 5 fresh drafts (Bandar-E
Mahshahr ~21.9h, Basrah ~13.1h, Deaver ~8.9h, Al Basrah ~5.2h, Tunis ~1.2h) are well under 48h —
clear. **Bulk-reject attempted:** `gh api -X PATCH gists/...` requires the `gh` CLI, confirmed
absent this session (`which gh` → command not found); no gist-write tool is exposed via the
GitHub MCP server tools loaded this session (repo/PR/issue/actions tools only, no gist scope).
Skipped per the hard constraints, logged rather than failing the cycle — **49th consecutive
skip** (May 13 → Jul 17). Operator: this draft has now sat unactioned longer than any prior
staleness candidate this routine has flagged; recommend rejecting it via dashboard.

### 2026-07-16 — Staleness bulk-reject: 1 strict candidate identified (4th consecutive cycle unactioned, oldest to date); write skipped (48th consecutive skip)

**Status:** 4 pending drafts reviewed (2 fresh; 2 carry-overs from Jul 11). 1 strict bulk-reject
candidate, unchanged identity from the last three cycles: **western Siberia fire cluster**
(`draft_20260711_062452_120`, created 2026-07-11T06:24:52Z, ~128.7h old at grading —
first flagged Jul 13 at ~56.6h, now the 4th consecutive cycle unactioned and the corpus's
oldest unactioned strict candidate to date). Text still reads "Three fire signals in the same
patch of western Siberia **today**" — present-tense, real-time-baked, now describing a fire
event over 5 days stale. Interior Alaska fire (`draft_20260711_062334_119`, same ~128.8h age)
contains no date/time language — clear under the established carve-out, consistent with every
prior ruling on this draft since Jul 11. Powderville and Oslo are both same-day fresh (~5.1h
and ~1.0h respectively) — clear. **Bulk-reject attempted:** `gh api -X PATCH gists/...` requires
the `gh` CLI, confirmed absent this session (`which gh` → command not found); no gist-write tool
is exposed via the GitHub MCP server tools loaded this session (repo/PR/issue/actions tools
only, no gist scope). Skipped per the hard constraints, logged rather than failing the cycle —
**48th consecutive skip** (May 13 → Jul 16). Operator should reject the western Siberia draft
via dashboard; it is now the single oldest unactioned item this routine has ever flagged.

### 2026-07-15 — Staleness bulk-reject: 1 strict candidate identified (3rd consecutive cycle unactioned); write skipped (47th consecutive skip)

**Status:** 6 pending drafts reviewed (0 fresh; 6 carry-overs from Jul 9–14). 1 strict
bulk-reject candidate: **western Siberia fire cluster** (`draft_20260711_062452_120`, created
Jul11T06:24:52Z, ~104.7h old, "Three fire signals in the same patch of western Siberia
**today**" — present-tense date-baked language, forecast event long over). Flagged Jul 13
(~56.6h) and Jul 14 (~80.6h), now unactioned for a **3rd consecutive cycle**. Interior Alaska
fire (same ~104h age) contains no date/time language and stays clear under the established
carve-out; Stevensville/Riyadh dust_event/Tepee Creek remain clear under the past-tense-record
carve-out regardless of age; Basrah is <9h old. **Write attempted and skipped:** `gh api -X
PATCH gists/...` requires the `gh` CLI, confirmed absent this session (`which gh` → command
not found); no gist-write tool is exposed via the GitHub MCP server tools loaded this session
(repo/PR/issue tools only, no gist scope). Per the hard constraints, logged rather than failing
the cycle — **47th consecutive skip** (May 13 → Jul 15). Operator should reject the western
Siberia fire cluster via dashboard; it has now sat unactioned across three grading cycles, the
longest-running unactioned candidate since the Basra-area cluster flagged Jul 1–6 (cleared by
the Jul 7 `main` merge / PR #385's forecast-elapsed auto-reject).

**Separately (not a staleness rejection, logging for the record):** Randolph, Utah
`all_time_high` (B+, graded Jul 14) and Ontario, Canada `fire` cluster (C+, graded Jul 14) are
both absent from today's pull — cause unconfirmed (bulk-reject, bulk-publish, or TTL/other
sweep not observable from the gist). This is the 3rd/4th instance of an unexplained
queue-contraction pattern this plan has logged, after Anchorage (Jul 10→11) and Ahvaz
(Jul 11→12); see `docs/DRAFT_CORPUS.md` Jul 15 entry, Followup #4.

### 2026-07-14 — Staleness bulk-reject: 1 strict candidate identified (2nd consecutive cycle unactioned); write skipped (46th consecutive skip)

**Status:** 8 pending drafts reviewed (3 fresh, created 2026-07-14, oldest ~9h/newest ~1h at
grading; 5 carry-overs from Jul 9–11, ~28h–80h old). 1 strict bulk-reject candidate, unchanged
from Jul 13 and now older: **western Siberia fire cluster** (created Jul11T06:24:52Z, ~80.6h
old, "Three fire signals in the same patch of western Siberia **today**" — present-tense
"today" now misdates the event by more than three days). Interior Alaska fire (same ~80.6h
creation window) still does not qualify — no date or time-of-day language. Stevensville,
Riyadh dust_event, and Tepee Creek remain clear under the established past-tense-record
carve-out regardless of age. Randolph, Basrah, and Ontario are all same-day fresh and clear.
**Write attempted and skipped:** `gh api -X PATCH gists/...` requires the `gh` CLI, confirmed
absent this session (`which gh` → command not found); no gist-write tool is exposed via the
GitHub MCP server tools loaded this session (repo/PR/issue tools only, no gist scope). Per the
hard constraints, logged rather than failing the cycle — **46th consecutive skip** (May 13 →
Jul 14). Operator should reject the western Siberia fire cluster via dashboard; it has now
been an identified strict candidate for 2 consecutive cycles without action.

### 2026-07-13 — Staleness bulk-reject: 1 strict candidate identified; write skipped (45th consecutive skip)

**Status:** 5 pending drafts reviewed — exact match to Jul 12's graded batch, no new drafts.
1 strict bulk-reject candidate identified: **western Siberia fire cluster** (created
Jul11T06:24:52Z, ~56.6h old, "Three fire signals in the same patch of western Siberia
**today**" — present-tense "today" now misdates the event by more than two days). Crosses
both the 48h mechanical threshold and carries real-time-baked content — the same two-part
strict test applied to every prior bulk-reject candidate in this log. Flagged as approaching
this line in the Jul 11 and Jul 12 entries; it has now arrived. Interior Alaska fire (same
~56.6h creation window) does not qualify — no date or time-of-day language at all. Stevensville
(~107.6h), Riyadh (~95.6h), and Tepee Creek (~76.0h) all remain clear under the established
past-tense-dated-report carve-out regardless of age. **Write attempted and skipped:**
`gh api -X PATCH gists/...` requires the `gh` CLI, confirmed absent this session (`which gh` →
command not found); no gist-write tool is exposed via the GitHub MCP server tools loaded this
session (repo/PR/issue tools only, no gist scope). Per the hard constraints, logged rather than
failing the cycle — **45th consecutive skip** (May 13 → Jul 13). Operator should reject the
western Siberia fire cluster draft via dashboard.

### 2026-07-12 — Staleness bulk-reject: 0 candidates; gh CLI absent (44th consecutive skip)

**Status:** 5 pending drafts reviewed (5 of Jul 11's 6, Ahvaz dropped out — see corpus entry).
Stevensville (~83.9h), Riyadh (~71.9h), and Tepee Creek (~52.3h) are all >48h old but each cites
a specific past date rather than real-time language — the established carve-out, unchanged from
every prior ruling on this distinction. Interior Alaska fire (~32.9h) is fresh and clear.
Western Siberia fire cluster (~32.9h) still contains "today" but remains under the 48h
threshold — same watch flagged Jul 11, now due around 2026-07-13T06:25Z if still pending.
**0 strict bulk-reject candidates.** `gh` CLI confirmed absent — 44th consecutive skip (May 13
→ Jul 12).

### 2026-07-11 — Staleness bulk-reject: 0 candidates; gh CLI absent (43rd consecutive skip)

**Status:** 6 pending drafts reviewed. Stevensville MD (~59.7h) and Riyadh dust_event
(~47.7h) are both past-tense dated reports with no real-time-baked language — the
established all_time_high/dust_event carve-out applies regardless of age. Tepee Creek MT
and Ahvaz Iran (~28.1h) and the 2 fresh fire drafts (~8.7-8.8h) are all well under 48h.
Ahvaz's forecast date (July 10) has elapsed by one day but the draft is under 48h — not a
strict candidate; flagged for the operator as a possible gap in PR #385's forecast-elapsed
auto-reject (see `docs/DRAFT_CORPUS.md` Jul 11 entry). 0 bulk-reject candidates by policy;
write path not attempted since nothing qualified. `gh` CLI confirmed absent (`which gh` →
command not found); no gist-write tool exposed via the GitHub MCP tools loaded this session.
43rd consecutive skip (May 13 → Jul 11).

### 2026-07-10 — Staleness bulk-reject: 0 candidates; gh CLI absent (42nd consecutive skip)

**Status:** 5 pending drafts reviewed — 2 carry-overs from Jul 9 (Stevensville MD, Anchorage
AK, ~35.7h old at grading, both historical-observation framing, no elapsed forecast date)
plus 3 fresh (Riyadh dust_event ~23.7h; Tepee Creek MT and Ahvaz Iran ~4h). None cross 48h.
Ahvaz's forecast date (July 10) is today — accurate, not stale. 0 bulk-reject candidates by
policy; write path not attempted since nothing qualified. `gh` CLI confirmed absent (`which
gh` → command not found) — 42nd consecutive skip (May 13 → Jul 10).

**Notable:** 2 of Jul 9's 2 drafts survive as carry-overs — first cycle since Jul 6 that
isn't a complete queue turnover (breaks the Jul 3→4/Jul 6→7/Jul 7→8/Jul 8→9 streak).

### 2026-07-09 — Staleness bulk-reject: 0 candidates; gh CLI absent (41st consecutive skip)

**Status:** 2 pending drafts reviewed, both created 2026-07-09 (~11-12h old at grading).
Neither crosses 48h; neither contains an elapsed forecast date (Stevensville all_time_high
cites a past observation date, July 5; Anchorage precipitation_extreme cites a past
observation date, July 7 — both historical, not forward-forecast). 0 bulk-reject
candidates by policy. `gh` CLI confirmed absent (`which gh` → command not found); no
gist-write tool exposed via the GitHub MCP tools loaded this session — 41st consecutive
skip (May 13 → Jul 9); write path not attempted (nothing qualifies this cycle regardless).

**Notable:** all 8 of Jul 8's pending drafts are gone from the queue — 4th complete
queue turnover event (after Jul 3→4, Jul 6→7, Jul 7→8). Cause unconfirmed from the gist
alone, consistent with all three prior turnover events.

### 2026-07-08 — Staleness bulk-reject: 0 candidates; gh CLI absent (40th consecutive skip)

**Status:** 8 pending drafts reviewed, all created 2026-07-08 (oldest ~12h, newest
~15min at grading). None cross 48h; none contain elapsed forecast dates (Typhoon Bavi's
`cyclone_land_threat` draft is correctly forecast-tense — "forecast to pass... in
roughly 60 hours," not a past-due date). 0 bulk-reject candidates by policy. `gh` CLI
confirmed absent (`which gh` → command not found); no gist-write tool exposed via the
GitHub MCP tools loaded this session — 40th consecutive skip (May 13 → Jul 8); write
path not attempted (nothing qualifies this cycle regardless).

**Notable:** all 6 of Jul 7's pending drafts are gone from the queue — 3rd complete
queue turnover event (after Jul 3→4 and Jul 6→7). Consistent with the pattern PR #385's
forecast-elapsed sweep established: drafts appear to clear the queue quickly once
graded/actioned rather than accumulating as carry-overs, though the exact mechanism
(publish vs. reject vs. TTL) remains unconfirmed from the gist alone.

### 2026-07-07 — Staleness bulk-reject: 0 candidates; queue turned over structurally (39th consecutive `gh` skip)

**Status:** 6 pending drafts reviewed, all created 2026-07-07 (oldest ~11h, newest ~15min
at grading). None cross 48h; none contain elapsed forecast dates. 0 bulk-reject
candidates by policy. `gh` CLI still absent — 39th consecutive skip (May 13 → Jul 7);
write path not attempted (nothing qualifies this cycle regardless).

**Notable:** the 2 strict candidates flagged Jul 6 ([4] Basrah, [6] Al Başrah al
Qadīmah `absolute_extreme`, both >48h old with elapsed forecast dates) are **gone from
the queue** as of this pull, along with all 13 other Jul-6 carry-overs — a complete
queue turnover. PR #385 ("forecast-elapsed sweep — elapsed-forecast drafts auto-reject,
the Basrah class," merged 2026-07-07T04:55:15Z) shipped a provenance-aware structural
fix for exactly this pattern at the triage drain step, hours before this grading run.
Whether that PR is what cleared them (vs. operator dashboard action, vs. an unrelated
TTL sweep) isn't directly observable from the gist alone, but the timing and the exact
match to the targeted failure class make it the most likely explanation. If confirmed
over subsequent cycles, this closes the operational (not voice-quality) half of the
Basra-area staleness problem this routine has flagged in every cycle since Jul 1.

### 2026-07-06 — Staleness bulk-reject: 2 strict candidates identified; write skipped (38th consecutive skip)

**Status:** 15 pending drafts reviewed — exact match to Jul 5's graded batch, no new drafts.
2 strict bulk-reject candidates identified: **[4] Basrah, Iraq `absolute_extreme`** (created
Jul4T06:55Z, ~56.2h old, "is forecast to hit 47°C (117°F) on July 4" — forecast date now 2 days
elapsed) and **[6] Al Başrah al Qadīmah, Iraq `absolute_extreme`** (created Jul4T10:16Z, ~52.8h
old, "forecast high of 47.4°C (117°F) on July 4" — same elapsed-forecast-date class). Both cross
48h **and** carry a forecast date that has already passed — the same Basra-area staleness class
flagged in the Jul 1–3 entries. **Write attempted and skipped:** `gh api -X PATCH gists/...`
requires the `gh` CLI, confirmed absent this session (`which gh` → command not found); no
gist-write tool is exposed via the GitHub MCP server tools loaded this session (repo/PR/issue
tools only, no gist scope). Per the hard constraints, logged rather than failing the cycle —
**38th consecutive skip** (May 13 → Jul 6). Operator should reject [4] and [6] via dashboard.
[15] Doha's forecast date (July 5) has also elapsed but sits at 25.2h — not yet a strict
candidate; watch for it crossing 48h at the next grading pull.

### 2026-07-05 — Staleness bulk-reject: 0 candidates; gh CLI absent (37th consecutive skip)

**Status:** 15 pending drafts reviewed (5 fresh, created 2026-07-05, oldest ~10h/newest
~15min at grading; 10 carry-overs from Jul 4, ~24h old). None cross 48h. The Doha
`absolute_extreme` draft forecasts "July 5" (today) — accurate, not stale. No bulk-reject
candidates by policy. Gist write not attempted (`gh api -X PATCH`) — `gh` CLI absent in
this remote execution environment, consistent with every cycle since May 13 (37th
consecutive skip). Per the hard constraints, this is logged and the cycle continues
rather than failing — operator should bulk-reject via dashboard if any of the 10 Jul-4
carry-overs are judged stale by the time this PR is reviewed.

### 2026-07-04 — Staleness bulk-reject: 0 candidates (all drafts same-day fresh); queue turnover noted separately

**Status:** 10 pending drafts reviewed, all created 2026-07-04 (oldest ~11h, newest
~15min at grading). None cross 48h; the two `absolute_extreme` drafts forecast "July 4"
(today) — accurate, not stale. No bulk-reject candidates by policy. Gist write not
attempted — nothing qualified. `gh` CLI absent, 36th consecutive skip (May 13 → Jul 4).

**Separately (not a staleness rejection, logging for the record):** all 20 drafts pending
as of Jul 3's grading — including the 4 drafts flagged as strict bulk-reject candidates
that cycle (Mediterranean SST, GMST marine_heatwave, Basrah 47.2°C, Al Baṣrah al Qadīmah
47°C) and 13 clean carry-overs — are absent from this pull. Whether this was the operator
acting on the repeated reject requests, a bulk-publish, or an automated TTL/other sweep is
not observable from the gist; see `docs/DRAFT_CORPUS.md` Jul 4 entry, Followup #1.

### 2026-07-03 — Staleness bulk-reject: 4 stale identified (2 promoted this cycle); gh CLI absent (35th consecutive skip)

**Status:** 20 pending drafts reviewed. 4 strict bulk-reject candidates (>48h old AND
real-time-baked or forecast-date-elapsed content):

| Draft ID | Created | Age | Staleness flag |
|---|---|---|---|
| `draft_20260628_040130_32` (Mediterranean SST) | 2026-06-28T04:01Z | ~131h | "running 3.54°C above its seasonal normal **today**" — flagged Jun 30/Jul 1/Jul 2, still unactioned (4th cycle) |
| `draft_20260628_171634_36` (GMST marine_heatwave) | 2026-06-28T17:16Z | ~118h | "**today's** reading is 20.961°C" — flagged Jul 1/Jul 2, still unactioned (3rd cycle) |
| `draft_20260630_213852_50` (Basrah, Iraq 47.2°C) | 2026-06-30T21:38Z | ~66h | Forecast was for June 30 (now 3 days elapsed); **newly crosses 48h this cycle** — was a "forecast-elapsed, not yet mechanically stale" observation on Jul 1/Jul 2, now a strict candidate |
| `draft_20260701_145246_52` (Al Baṣrah al Qadīmah 47°C) | 2026-07-01T14:52Z | ~48h | Forecast was for July 1 (now 2 days elapsed); **newly crosses 48h this cycle** |

**Near-stale, flagging proactively:** `draft_20260701_214913_55` (Basrah, Iraq 48°C forecast for
July 1, ~41h old) — forecast date elapsed 2 days ago, same as the two promoted above, but hasn't
yet crossed the 48h mechanical threshold. Will be a strict candidate next cycle; recommend the
operator reject it now rather than wait.

**Why skipped:** `gh` CLI not available in this remote execution environment — 35th consecutive
skip (May 13 → Jul 3). Operator must reject all 4 (5 including the near-stale one) via dashboard.
Two of today's four candidates ([11], [13]) are newly promoted from "forecast-date-elapsed but
under 48h" observations logged on Jul 1/Jul 2 — the mechanical clock has now caught up to what
was already true in substance. No other pending drafts contain "today"/"tonight"/forecast-for-today
language; the fresh Canadian Arctic fire pair and Typhoon Bavi are all under 20h old and clear.

### 2026-07-02 — Staleness bulk-reject: 2 stale identified; gh CLI absent (34th consecutive skip)

**Status:** 17 pending drafts reviewed. 2 stale candidates (same 2 as Jul 1, now older and still
unactioned):

| Draft ID | Created | Age | Staleness flag |
|---|---|---|---|
| `draft_20260628_040130_32` (Mediterranean SST) | 2026-06-28T04:01Z | ~107h | "running 3.54°C above its seasonal normal **today**" — flagged Jun 30, Jul 1, still unactioned (3rd cycle) |
| `draft_20260628_171634_36` (GMST marine_heatwave) | 2026-06-28T17:16Z | ~94h | "**today's** reading is 20.961°C" — flagged Jul 1, still unactioned (2nd cycle) |

Bulk-reject attempted via `gh api -X PATCH gists/...` — `gh` CLI not installed in this remote
execution environment. 34th consecutive skip (May 13 → Jul 2). Operator must reject both via
dashboard. Non-flagged but notable: [11]/[13]/[16] — all 3 `absolute_extreme` Basra-area drafts
now reference forecast dates that have elapsed (June 30, July 1, July 1) but none is yet 48h old
(~41h/~24h/~17h) — logged as a freshness observation in `docs/DRAFT_CORPUS.md`, not a bulk-reject
candidate under the mechanical age rule. [8] Rocky Mountains, Colorado fire crossed 48h (~65h) for
the first time this cycle but contains no explicit "today"/present-tense real-time language —
also logged as an observation, not a reject candidate. All other pending drafts use past-tense or
explicitly-dated framing with no "today"/"tonight"/forecast-for-today language.

### 2026-07-01 — Staleness bulk-reject: 2 stale identified; gh CLI absent (33rd consecutive skip)

**Status:** 14 pending drafts reviewed. 2 stale candidates:

| Draft ID | Created | Age | Staleness flag |
|---|---|---|---|
| `draft_20260628_040130_32` (Mediterranean SST) | 2026-06-28T04:01Z | ~83h | "running 3.54°C above its seasonal normal **today**" — flagged stale at Jun 30 grading (~59h), still unactioned |
| `draft_20260628_171634_36` (GMST marine_heatwave) | 2026-06-28T17:16Z | ~70h | "**today's** reading is 20.961°C" — was approaching 48h at Jun 30 grading (~46h), now over |

Bulk-reject attempted via `gh api -X PATCH gists/...` — `gh` CLI not installed in this remote
execution environment. 33rd consecutive skip (May 13 → Jul 1). Operator must reject both via
dashboard. Non-flagged drafts: [11] Basrah forecast (`draft_20260630_213852_50`) references a
forecast date (June 30) that has already elapsed but is only ~17h old — does not meet the
mechanical 48h threshold, logged as a freshness observation in `docs/DRAFT_CORPUS.md` rather
than a bulk-reject candidate. All other pending drafts use past-tense or explicitly-dated
framing with no "today"/"tonight"/forecast-for-today language.

### 2026-06-30 — Staleness bulk-reject: 1 stale identified; gh CLI absent (32nd consecutive skip)

**Status:** 10 pending drafts reviewed. 1 stale candidate: Mediterranean regional_sst_anomaly
(created 2026-06-28T04:01Z, ~59h old at grading time ~15:00 UTC Jun 30, contains "today"
language — staleness positive). Excluded from A-rate denominator. GMST marine_heatwave
(created 2026-06-28T17:16Z, ~45.7h old) contains "today's reading" — approaching 48h threshold;
operator should publish promptly. `gh` CLI absent in remote execution environment; 32nd
consecutive skip (May 13 → Jun 30). Mediterranean draft flagged for operator manual rejection
via dashboard.

### 2026-06-27 — Staleness bulk-reject: 0 candidates; gh CLI absent (13th consecutive skip)

**Status:** 2 pending drafts reviewed. Draft [1] (fire, created 2026-06-27T06:57Z, ~8h old at grading) contains "today" — real-time-baked. Well under the 48h policy threshold; not a staleness candidate. Will cross the threshold ~2026-06-28T06:57Z if unpublished. Draft [2] (precipitation_extreme, created 2026-06-27T10:17Z) uses past-tense framing ("received") — no real-time-baked content; clear. 0 drafts trigger the staleness policy. `gh` CLI absent in remote execution environment; 13th consecutive skip (May 13 → Jun 27).

### 2026-06-28 — Staleness bulk-reject: 0 candidates; gh CLI absent (30th consecutive skip)

**Status:** 7 pending drafts reviewed; 0 candidates. Carry-over [1] (fire, "today" baked, ~32h old) not yet at 48h threshold — crosses at ~Jun 29T07:00Z; operator should verify/reject if not published. Carry-over [2] (Amsterdam, no date-bake, ~29h) clear. Fresh [3] (Taiz, "June 27" baked, ~22h) not yet at 48h — crosses at ~Jun 29T17:00Z. All other fresh drafts <12h old. `gh` CLI absent — 30th consecutive skip (May 13 → Jun 28; Jun 27 run's "13th" was a tracking bug; authoritative count from Jun 26 = 29th + 1).

### 2026-06-26 — Staleness bulk-reject: 0 candidates; gh CLI absent (29th consecutive skip)

**Status:** 3 pending drafts reviewed (Amsterdam, Aktobe, Anchorage — all created
2026-06-26T04:00–07:59Z, < 48h old at grading time ~15:00 UTC). No real-time-baked language
("today"/"tonight"/"forecast") in any draft. **0 staleness candidates.** Operator note: all 3
Jun 26 drafts approach the 48h threshold ~Jun 28T04:00–07:59Z — post or reject before then.
`gh` CLI absent — 29th consecutive skip (May 13 → Jun 26).

### 2026-06-24 — Staleness bulk-reject: 0 qualifying candidates; gh CLI absent (27th consecutive skip)

**Status:** 2 pending drafts reviewed. Draft [1] (Randolph UT monthly_high, created
2026-06-24T07:46:05Z) — "June 20" is a historical record date, no real-time-baked
language. Not a staleness candidate. Draft [2] (Al Aḥmadī Kuwait air_quality_hazard,
created 2026-06-24T14:50:41Z) — contains "June 24." < 48h old at grading time; not a
staleness candidate yet. **Operator: Draft [2] crosses 48h threshold ~Jun 26T14:50 UTC
— post or reject before then.** Mediterranean SST (`draft_20260622_171200_17`, status=
approved) is ~46h old at grading time (~15:00 UTC), crossing 48h at ~Jun 24T17:12 UTC.
**Operator: post or reject Mediterranean SST within ~2h of this run.** `gh` CLI absent —
27th consecutive skip (May 13 → Jun 24).

### 2026-06-23 — Staleness bulk-reject: 0 pending drafts; gh CLI absent (26th consecutive skip)

**Status:** 0 pending drafts at runtime — bulk-reject policy not triggered. Mediterranean SST (`draft_20260622_171200_17`, created Jun 22T17:12Z, status=approved) contains "today" anchor; crosses the 48h staleness threshold at Jun 24T17:12Z. Policy applies to pending drafts — operator should post or reject before Jun 24T17:12Z. Columbus GA (`draft_20260622_170931_16`) and Cope Rch TX (`draft_20260622_193302_18`) are status=posted — not candidates. Chesnee SC (`draft_20260610_155509_26`, status=approved) references "June 6" as historical date — no real-time-baked language, not a candidate. `gh` CLI absent in remote execution environment — 26th consecutive skip (May 13 → Jun 23). No operator action needed before Jun 24T17:12Z.

### 2026-06-22 — Staleness bulk-reject: 0 candidates; queue empty; gh CLI absent (25th consecutive skip)

**Status:** 0 pending drafts — queue empty (4th consecutive day). Retroactive Barrow 7-day draft (rejected Jun 18T19:42Z, ~4h after creation) well under 48h threshold. `gh` CLI absent — 25th consecutive skip (May 13 → Jun 22). No operator action needed.

### 2026-06-21 — Staleness bulk-reject: 0 candidates; queue empty; gh CLI absent (24th consecutive skip)

**Status:** 0 pending drafts — queue empty. Last resolved drafts were the 3 Jun 18 precipitation_extreme entries, all operator-rejected (logged in Jun 19 rejection event). No pending drafts to evaluate for staleness. `gh` CLI absent in remote execution environment — 24th consecutive skip (May 13 → Jun 21). No operator action needed.

### 2026-06-19 — Staleness bulk-reject: 0 candidates; queue empty; gh CLI absent (23rd consecutive skip)

**Status:** 0 pending drafts — queue empty. All 3 Jun 18 precipitation_extreme drafts are now
status=rejected in gist: Barrow AK daily (71.2mm, Jun 18T04:14Z), Amsterdam 7-day (314.4mm,
Jun 18T12:02Z), Barrow AK 7-day (427.5mm, Jun 18T15:43Z — never graded). Rejections appear
operator-initiated (all < 24h old at time of rejection, TTL not reached). `gh` CLI absent in
remote execution environment — 23rd consecutive staleness skip (May 13 → Jun 19). No operator
action needed on staleness grounds; operator has already cleared the queue.

### 2026-06-18 — Staleness bulk-reject: 0 candidates; gh CLI absent (22nd consecutive skip)

**Status:** 2 pending drafts reviewed. Draft [1] (Barrow Alaska, created 2026-06-18T04:14Z,
10.8h old) references "June 16" as historical observation date — past-tense, no "today" or
forecast language. Draft [2] (Amsterdam, created 2026-06-18T12:02Z, 3.0h old) uses past-tense
"received" — no real-time-baked language. Neither qualifies under the staleness policy. `gh`
CLI absent in remote execution environment — 22nd consecutive skip (May 13 → Jun 18). No
operator action needed.

### 2026-06-16 — Staleness bulk-reject: 0 pending drafts; gh CLI absent (20th consecutive skip)

**Status:** 0 pending drafts — staleness policy not triggered. `gh` CLI absent in remote
execution environment; 20th consecutive skip (May 13 → Jun 16). No operator action needed.

### 2026-06-15 — Staleness bulk-reject: 0 pending drafts; gh CLI absent (19th consecutive skip)

**Status:** 0 pending drafts — staleness policy not triggered. One draft in "approved" status
(`draft_20260610_155509_26`, Chesnee SC monthly_low, created 2026-06-10T15:55Z, approved
2026-06-10T16:17Z) lacks `posted_at` and tweet_id — possible posting failure not related to
staleness policy. `gh` CLI absent in remote execution environment; 19th consecutive skip
(May 13 → Jun 15). No operator dashboard action needed on staleness grounds; operator should
verify whether Chesnee SC tweet was actually sent.

### 2026-06-14 — Staleness bulk-reject: 0 candidates; gh CLI absent (18th consecutive skip)

**Status:** 2 pending carry-over drafts reviewed. Draft [1] (Red Dog Mine monthly_low, created
Jun 13T08:03Z) ~31h old — under 48h threshold; "on June 9" is historical observation date. Draft
[2] (Riyadh dust_event, created Jun 13T08:05Z) ~31h old — "June 13" is historical measurement
date reference, consistent with prior corpus rulings. Neither draft triggers the staleness
policy. `gh` CLI absent; 18th consecutive skip (May 13 → Jun 14). No operator action needed.

### 2026-06-13 — Staleness bulk-reject: 0 candidates; gh CLI absent (17th consecutive skip)

**Status:** 2 pending drafts reviewed. Both created 2026-06-13T08:03-08:05Z (< 8h old at
grading) — well under the 48h threshold. Draft [2] (Riyadh dust_event) bakes "June 13"
in the text; not stale by policy (under threshold). Neither draft contains
"today/tonight/forecast" language beyond the date reference in draft [2]. 0 candidates.
`gh` CLI absent; 17th consecutive skip (May 13 → Jun 13). No operator action needed.

### 2026-06-12 — Staleness bulk-reject: 0 candidates; gh CLI absent (16th consecutive skip)

**Status:** 0 pending drafts — nothing to evaluate. Jun 7 Barrow draft is now status='posted'.
No real-time-baked language in queue (queue is empty). `gh` CLI absent in remote execution
environment; 16th consecutive skip (May 13 → Jun 12). No operator action needed.

### 2026-06-11 — Staleness bulk-reject: 0 candidates; gh CLI absent (15th consecutive skip)

**Status:** 0 pending drafts. Queue confirmed empty since Jun 9 run. No candidates. `gh` CLI
absent; 15th consecutive skip (May 13 → Jun 11). No operator action needed.

### 2026-06-10 — Staleness bulk-reject: 0 candidates; gh CLI absent (14th consecutive skip)

**Status:** 0 pending drafts. Queue empty (Barrow AK draft cleared Jun 9). No candidates.
`gh` CLI absent; 14th consecutive skip (May 13 → Jun 10). No operator action needed.

### 2026-06-09 — Staleness bulk-reject: 0 candidates; gh CLI absent (13th consecutive skip)

**Status:** 0 pending drafts — Barrow AK precipitation_extreme cleared between Jun 8 and Jun 9
(~59h old at clearing; under 48h threshold was missed in Jun 8 review; cleared by operator).
`gh` CLI absent; 13th consecutive skip (May 13 → Jun 9). No operator action needed.

### 2026-06-17 — Staleness bulk-reject: 0 pending drafts; gh CLI absent (21st consecutive skip)

**Status:** 0 pending drafts at runtime — staleness policy not triggered. Urumqi dust_event
(posted Jun 17T12:27Z, no "today/forecast" language) was already posted before routine ran.
`gh` CLI absent (21st consecutive skip, May 13 → Jun 17). No operator action needed.

### 2026-06-08 — Staleness bulk-reject: 0 candidates; gh CLI absent (12th consecutive skip)

**Status:** 1 pending draft reviewed. Draft [1] (Barrow Alaska precipitation_extreme,
created 2026-06-07T04:07:40Z) is ~35h old — under 48h threshold — and contains no
real-time-baked language (past-tense "received," no "today" or forecast anchors). Not
a staleness candidate. `gh` CLI absent in remote execution environment; 12th consecutive
skip (May 13 → Jun 8). No operator action needed.

### 2026-05-24 — Staleness bulk-reject: no qualifying candidates; gh CLI absent (8th consecutive skip)

**Status:** 13 pending drafts reviewed. None contain real-time-baked language ("today,"
"tonight," "forecast to hit today"). Chuuk/Bethel cite "May 9" as a historical observation
date (consistent with all prior staleness rulings). Coral DHW drafts use cumulative metric
language without date-baking. Snow extreme drafts ("fell over 3 days") similarly clear.
No drafts trigger the staleness policy. `gh` CLI not installed in managed remote execution
environment — 8th consecutive skip (May 13 through May 24). No operator dashboard action
needed on staleness grounds, but operator should verify that 9-day-old coral DHW values
(May 15 drafts) still reflect current NOAA CRW readings before publishing.

### 2026-05-23 — Staleness bulk-reject: not triggered (0 new candidates; 5 prior stale fire drafts cleared by operator on 2026-05-22)

**Why not triggered:** All 13 remaining drafts reviewed. No draft meets both criteria
(>48h AND real-time-baked language). DHW coral drafts use multi-week accumulation metrics
with no "today" or date-baked language; consistent with all prior rulings since 2026-05-15.
Snow drafts reference a completed event ("fell over 3 days") — historical framing, not
forecast-to-hit-today. Monthly-high and monthly-low drafts reference "May 9" as the
observation date of a record, not as "today." 0 candidates meet the threshold.

`gh` CLI unavailable in this remote execution environment (consistent with all cycles
since 2026-05-13). No write attempted; nothing to write.

Operator note: 5 stale fire drafts (Mali + Campeche + Mongolia + BC + Siberia) were
cleared on 2026-05-22 per BRIEFING.md — queue 18 → 13. No further operator action
required on staleness this cycle. Oldest remaining drafts are 8 coral DHW drafts from
2026-05-15 (~8 days old); verify DHW freshness before posting.

### 2026-05-22 — Staleness bulk-reject: skipped (gh CLI not found; 7th consecutive skip)

**Stale drafts identified (5):**

| Draft ID | Created | Age | Staleness flag |
|---|---|---|---|
| `draft_20260512_180320_159` | 2026-05-12T18:03Z | ~10 days | Present-tense "is radiating" — fire signal, almost certainly ended |
| `draft_20260512_212510_160` | 2026-05-12T21:25Z | ~10 days | Present-tense "is radiating" — same |
| `draft_20260513_103313_162` | 2026-05-13T10:33Z | ~9 days | Present-tense "is radiating" — same |
| `draft_20260514_211447_164` | 2026-05-14T21:14Z | ~8 days | Explicit "burning today" — directly date-baked |
| `draft_20260518_180600_112` | 2026-05-18T18:06Z | ~4 days | Explicit "detected in eastern Siberia today" — date-baked |

**Why skipped:** `gh` CLI not installed in this remote execution environment. Seventh
consecutive cycle (May 13 → May 22) where staleness bulk-reject has been attempted and
skipped. Operator must manually reject these 5 drafts via dashboard. **Additionally:**
the 8 coral bleaching drafts (IDs 135–142, created 2026-05-15) are now 7 days old — DHW
accumulation values may no longer reflect current reef stress. Not bulk-reject candidates
per policy (no "today" language; DHW is multi-week metric), but operator should verify
freshness before publishing.

### 2026-05-20 — Staleness bulk-reject: skipped (gh CLI unavailable); Draft 18 newly stale

**Why:** `draft_20260518_180600_112` (Siberia fire, "detected in eastern Siberia today",
created 2026-05-18T18:06Z) crosses the 48-hour threshold for the first time (~69h old at
grading). Explicit "today" language = staleness-positive. Added to operator reject list.
`draft_20260514_211447_164` (BC fire, "burning today") remains flagged from prior cycles
(7 days old). Fire drafts `draft_20260512_180320_159` (Mali), `draft_20260512_212510_160`
(Campeche), `draft_20260513_103313_162` (Mongolia) are ~180–192h old with present-tense
satellite detection framing — operator should reject all three via dashboard.
Bulk-reject attempted via `gh api -X PATCH` — `gh` CLI not installed in remote execution
environment. All 5 require operator dashboard action.

### 2026-05-19 — Staleness bulk-reject: skipped (gh CLI not found in cloud env)

**Why:** 1 draft identified for staleness rejection: `draft_20260514_211447_164` (BC fire,
"burning today" baked from 2026-05-14T21:14Z — 114 hours old at grading). Bulk-reject
attempted via `gh api -X PATCH gists/...` — `gh` command not found in managed remote
execution environment. Operator action required: reject `draft_20260514_211447_164` via
dashboard or direct Gist edit. Additional observation: 7 coral drafts (Drafts 7–13) are
4–7 days old with present-tense DHW accumulation claims ("has accumulated X°C-weeks") that
may no longer reflect current DHW values; they lack explicit "today" language and were not
bulk-rejected per policy, but operator should review for accuracy before posting.

### 2026-05-18 — Staleness bulk-reject: skipped (`gh` CLI unavailable)

**Why:** 4 fire drafts are > 48 hours old with real-time-baked content and should be
rejected. Stale candidates:

| Draft ID | Created | Age | Staleness flag |
|---|---|---|---|
| `draft_20260512_180320_159` | 2026-05-12T18:03Z | 141h | Present-tense "is radiating" — active fire signal, almost certainly ended |
| `draft_20260512_212510_160` | 2026-05-12T21:25Z | 138h | Present-tense "is radiating" — same |
| `draft_20260513_103313_162` | 2026-05-13T10:33Z | 124h | Present-tense "is radiating" — same |
| `draft_20260514_211447_164` | 2026-05-14T21:14Z | 90h | Explicit "burning today" — directly date-baked |

Bulk-reject attempted via `gh api -X PATCH` — `gh` CLI not installed in this execution
environment. Operator must manually reject these 4 drafts via the dashboard bulk-reject
API or individual reject buttons. Coral bleaching drafts (7–14, 82–84h old, created
2026-05-15) were evaluated but NOT flagged: DHW accumulation is a multi-week metric with
no "today" or "forecast" language; the general fact (reef system reached X°C-weeks) remains
valid. Temp-record drafts (Bethel Maine, Chuuk FSM) also not flagged: specific past dates
("hit 28°F on May 9") are historical records, not "forecast to hit today."

### 2026-05-17 — Staleness bulk-reject: skipped (gh CLI unavailable)

**Stale drafts identified (4):**
- `draft_20260512_180320_159` — Mali fire, "is radiating", created May 12 (~119h old)
- `draft_20260512_212510_160` — Campeche fire, "is radiating", created May 12 (~117h old)
- `draft_20260513_103313_162` — Mongolia fire, "is radiating", created May 13 (~102h old)
- `draft_20260514_211447_164` — BC fire, "burning today" (explicit date baked), created May 14 (~66h old)

**Why skipped:** `gh` CLI not installed in this remote execution environment. Gist write not
possible. Operator should bulk-reject these four fire drafts via the dashboard. The Chuuk and
Bethel drafts are NOT stale — they reference historical observation dates (May 9), not "today."
Coral bleaching drafts [7]-[14] are ~60-70h old but contain no real-time-baked date language.

### 2026-05-16 — Staleness bulk-reject: skipped (no qualifying drafts; gh CLI unavailable)

**Why:** 14 pending drafts reviewed. No draft meets both criteria (>48h AND real-time-baked
content). Draft [6] BC fire has "burning today" language but is only ~42 hours old at grading
time (created 2026-05-14T21:14Z). Drafts [1]-[4] are >48h old but use present-tense satellite
detection framing without "today/tonight/forecast" language — per the May 13 grading agent's
precedent, these do not trigger the staleness policy. Gist write skipped: `gh` CLI not available
in the remote execution environment. Operator should bulk-reject via dashboard if manual staleness
cleanup is desired on drafts [1]-[4] (Mali, Campeche, Chuuk, Mongolia, all May 12-13).

### 2026-05-15 — Staleness bulk-reject: not applicable + gist write blocked

**Why not applicable:** 14 pending drafts reviewed. Drafts 1-4 (carryovers, 2-3 days old) use present-tense satellite-detection framing with no "today"-baked content; Chuuk "May 9" is an observation date, not a "today" reference (same ruling as 2026-05-13 review). No draft qualifies under the "forecast-to-hit-today, dated references" criterion. **Gist write status:** `gh` CLI not available in this remote exec environment; `curl` to REST API returns 403 rate-limited. Staleness write would have been a no-op regardless.

### 2026-05-14 — Staleness bulk-reject: not needed; gh CLI unavailable

**Why:** 5 pending drafts; 0 are >48h old. Drafts [1]-[2] (fire, created 2026-05-12) are
the oldest at ~42-45h but contain only seasonal framing ("May sits at the tail of the dry
season"), not forecast-to-hit-today content — no staleness trigger. Drafts [3]-[5] all
<30h old. Staleness rejection criteria not met on any draft. Additionally, `gh` CLI is not
present in the grading environment (command not found); even if rejection were warranted,
the gist write path would need the git-based fallback or operator action via dashboard.
Operator note: staleness bulk-reject skipped — gh CLI unavailable; operator should
bulk-reject via dashboard if needed.

### 2026-05-13 — Staleness bulk-reject: not needed (no stale drafts)

**Why:** 4 pending drafts, all within 48 hours of creation (oldest: 2026-05-12T18:03Z,
~16 hours at time of grading). None contain real-time-baked content ("forecast to hit
today", "It is May 13", etc.) — fire drafts use present-tense satellite-detection framing
with no date baked in; Chuuk monthly_high references "May 9" as the observation date of
a record, not as "today." No staleness rejection triggered. Gist write not attempted.

### 2026-05-12 — Staleness bulk-reject: skipped (0 pending drafts)

**Why:** No pending drafts in queue; nothing to evaluate for staleness. Gist write not
attempted. Operator note resolved end-of-day 2026-05-12: both source degradations
(`ocean_sst` infinite redirects, `river_gauges` empty responses) are now fixed in PR #82
(User-Agent header + graceful degradation respectively). The four classes of writer/fact-
check kills that produced 0 drafts today are also addressed (PR #82 station-name regex,
PR #80 FRP bundle-side rounding, PR #76 length retry + KILL, PR #82 JSON-parse retry +
KILL). The texts and full grading commentary live in `docs/DRAFT_CORPUS.md`. This section
logs the rejection EVENT (when, why, count) so the operational history is traceable.

### 2026-04-26 — Bulk-reject 14 stale pending drafts

**Why:** All 14 drafts had real-time content baked into their text ("forecast to hit X today" / "set just last year in 2024" / "It is April 26"). Posted now they would read as wrong-day, past-tense, or confused. The window closed. Plus posting is paused until the resumption bar is cleared, so even fresh-baked versions of these wouldn't ship today. Rejected to clean the queue and give tomorrow's grader a clean baseline.

The 14 rejected drafts (preserved here for longitudinal comparison; full grading commentary in `docs/DRAFT_CORPUS.md`):

| Draft ID | Created | Type | Grade | Text |
|---|---|---|---|---|
| `draft_20260424_075424_119` | 2026-04-24 | fire | A- | New South Wales. A 327 MW fire today. The bushfire season here used to know when to quit. It's April. |
| `draft_20260424_154638_122` | 2026-04-24 | record | B+ | Kampung Baru Subang, Malaysia forecast to hit 94.1F today. The calendar date record from 1998 was 89.6F. Back then, Windows 98 was new. |
| `draft_20260424_190831_123` | 2026-04-24 | record | A- | Navi Mumbai is on pace for 106.7F today. That's 4.5F hotter than its record for this date, set just last year in 2024. |
| `draft_20260425_043325_124` | 2026-04-25 | record | B+ | Lucknow is forecast to hit 110.8F today. That beats its calendar record from 1999. Before Y2K was a real worry. |
| `draft_20260425_074401_125` | 2026-04-25 | record | B | Manchester forecast: 68.7F today. That beats the previous record for this date by nearly 3 degrees. The old mark of 66.0F was set in 2004, the year before YouTube. |
| `draft_20260425_184310_126` | 2026-04-25 | fire | A- | 404 MW of fire in Mali's Western Sahel. The land has been parched for months, and the HOT season has barely started. It's April. |
| `draft_20260425_184356_127` | 2026-04-25 | fire | C+ | A fire burning in Mali right now is radiating 404 MW of heat. The last rain fell there in October. That was 6 months ago. |
| `draft_20260426_222756_129` | 2026-04-26 | record | B+ | Petaling Jaya is forecast to hit 93.6F today. The record for this date was 89.2F — set in 2023, back when Hollywood writers were on strike. That gap is 4.4 degrees. |
| `draft_20260426_222959_130` | 2026-04-26 | fire | A- | Mali's Western Sahel is burning. A 291 MW fire is active in a landscape where the burning season typically peaks in January and ends by February. It is April 26. |
| `draft_20260426_223024_131` | 2026-04-26 | fire | B+ | 379 megawatts of heat radiating from the State of Mexico highlands right now. Satellite confidence: 95%. The summer monsoon that extinguishes these fires is still weeks away. |
| `draft_20260427_120825_132` | 2026-04-27 | record | C+ | Jacobabad is forecast to hit 114.1F today. The old record for this date was 112.1F. That record was set in 2022. It has only been the record since Elon Musk bought Twitter. |
| `draft_20260427_193214_134` | 2026-04-27 | monthly_high | B | Bukit Rahman Putra is forecast to hit 94.5F today. If it holds, that breaks an April record that has stood since 2016 — the year Pokémon GO had everyone walking outside. The new high: 94.5F. The old one: 93.7F. |
| `draft_20260427_230708_137` | 2026-04-27 | fire | B- | A 298 MW fire signature just appeared in central Mexico. Satellite confidence is 95 percent. The historical peak for fire activity in this region is still three weeks away. The rainy season does not typically begin until June. |
| `draft_20260427_230744_138` | 2026-04-27 | fire | B | Mexico State is radiating 258 MW of energy. 95% satellite confidence. The region's dry season doesn't break until late May. It is only April 27. |

**Notable:** four of these (NSW, Navi Mumbai, Mali Western Sahel "is burning", Mali "HOT season") were A- grades — they would have shipped if posting weren't paused AND if they were still timely. The pause + the staleness combine to disqualify even the strong drafts.

### 2026-04-26 — Bulk-reject 4 D-range fire drafts (earlier same day)

**Why:** humor-lens evaluation flagged banned-formula openers, stranded misdirection, and Wodehouse-rule violations. Detail in `docs/DRAFT_CORPUS.md` Apr 27 humor-lens section. Drafts:
- `draft_20260427_193501_136` — D- — "A wildfire burning in Mexico State is radiating 281 MW... pointed at the sky."
- `draft_20260427_193333_135` — D — "A wildfire in Mexico state is radiating 382 MW... commercial nuclear reactor outputs around 3,000 MW. This fire is running at roughly one-eighth of that — from a forest."
- `draft_20260427_120948_133` — D — "A single fire in central India is radiating 274 MW..."
- `draft_20260426_110808_128` — D — "A single wildfire in central India is pushing 297 MW of radiative power..."

### 2026-04-24 — Bulk-reject all 35 from Apr 24 corpus

**Why:** End of Apr 24 session, after the corpus grading exercise that established the eval baseline. All 35 drafts in queue were rejected to start fresh under voice engine v2 (which shipped same day). Texts preserved in `docs/DRAFT_CORPUS.md` Apr 24 section.

## How this file is used

- **Update after every grading cycle** — append a row to the A-rate table with that cycle's date, grade distribution, and notes.
- **Update after every bulk-reject event** — log the count, reason, and IDs (or a corpus reference) under the rejection events section.
- **Read before any posting decision** — has the trend cleared 50% sustained? If yes, resume. If no, the voice work continues.
- **Scheduled grader output** — the autonomous grading agent (next fires 2026-04-27 06:00 UTC) should append its own row to this table when it grades a fresh corpus cycle.
