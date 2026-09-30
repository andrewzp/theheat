# GDACS current episode qualification

The RSS current-alert lane previously selected overall alert severity. That can
represent an earlier episode even when the currently reported episode is below
the selection threshold. A recent catalog update alone cannot establish current
activity or intensity.

The parser now requires explicit `iscurrent=true`, a recognized episode alert
level and a nonblank episode identity. The selected episode must meet the caller's
severity threshold and cannot exceed the source's overall level. An Orange episode
under an overall Red alert may qualify for an Orange caller; the event and bundle
headline then say Orange. Overall source history remains separate provenance.

Diagnostics retain overall counts, add episode/current distributions, and distinguish
inactive, unverified, inconsistent and below-threshold candidates. The examined
candidate union includes either level above threshold, so an elevated episode under
a lower overall alert cannot disappear as healthy absence. Each qualification
failure counts once; structural quarantine takes status precedence and publication
withholding remains a separate count. The runner exposes gaps with zero candidates.

Raw numeric severity and descriptive text remain available, labeled as unqualified
source metrics. This adapter supplies no qualified wind-advisory time or averaging
period. Bounded local checks reject numeric wind-speed and Category 1–5 assertions
in RSS cyclone copy before paid checks. Actual GDACS disaster-type fields, including
retained facts on recheck, now also route through the existing dated landfall rule.
Independent NHC/JTWC advisory products retain their ordinary mandatory checks.

Synthetic tests cover selection and threshold behavior, malformed/absent flags,
contradictions, current versus publication time, diagnostic precedence, intern
provenance, zero drafting for withheld alerts, zero paid checks for recognizable
unsafe copy, and all mandatory checks for eligible controls. Added eligibility
fields in older public fixtures are explicitly synthetic; historical source
qualification is not inferred from them.

Lexical rejection is not complete semantic entailment. Passing local rules does
not approve a draft. Event IDs retain their existing opaque behavior; cross-episode
identity, primary JSON qualification, scientific wind-advisory integration and
measured coverage remain separate work. No endpoint, prompt, model, sample count,
publishing flag or retained production draft is changed. Fewer eligible alerts in
an offline replay do not establish absent impacts or improved global recall.
