# Reject known-invalid copy before paying for downstream checks

The existing main drafting stage now runs forbidden-claim/cross-signal rules and
the fact checker's deterministic rejection boundary before the safety model.
Recognizable unsupported incident/record/forecast/moisture claims, reused text,
malformed bundles and invalid text can stop without paying for downstream checks.
Scientific rules and evidence thresholds are unchanged.

`local_rejection` returns a rejection or None. None means models are still needed,
never factual certification or approval. The full fact checker independently runs
the same boundary again, so a later memory change cannot reuse earlier eligibility.
Eligible text still passes safety, full factual checking and the configured critic
on the exact selected text. Revised text follows that same path. Existing optional
multi-sample slate selection remains before this stage; no added savings are
claimed for that earlier critic call. The routine default remains one sample.

Simultaneous failures can now surface their deterministic cause before a safety
failure. Positive orchestration fixtures were corrected where they had labeled
thermal pixels as incidents or forecasts as observed records while mocking the
fact checker. Explicit synthetic incident evidence stays a fixture, not a source
certification or production fallback. Negative examples exercise the real gates.

17 new cases, 146 focused and 4,478 full offline Python tests pass (41 paid excluded).
Ruff, mypy over 150 source files, generated contracts and whitespace checks pass.
All 294 dashboard tests and the locked Next.js 15.5.25 build pass. One existing
Google SDK warning remains. No interface layout changed or new browser QA claimed.

The frozen private historical run has no unexpected observations. It verifies
existing deterministic evidence safeguards with explicitly injected writer/safety
results and intercepts provider access; it does not measure model writing quality.
The 63-text corpus remains classified by publication evidence, with all prior
source/QC/selected-view limits. No exact corpus text appears in the added diff.

This change alters policy identity, invalidating old approval bindings as intended.
The regenerated dashboard manifest requires manual deployment after authorized
release. Local validation is not remote CI, deployment, observed production
recovery or a measured bill reduction.
