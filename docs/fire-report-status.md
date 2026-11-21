# Reading saved incident-report status

The Sources page describes a saved NIFC incident-size collection. It does not
perform a live availability check, measure current fire size, or establish
complete US fire coverage.

“Incident reports held” means that the saved census records rejected report
rows, an evidence-admission refusal, or a provider truncation marker. Qualified
report rows and queued candidates are shown separately. A qualifying report
need not become a candidate: size tiers, duplicates and selection still apply.
When candidates were queued, “Supplying candidates” remains the outcome and
the report census is shown alongside it. Neither outcome means a draft or post
exists.

“Incident reports checked” means the retained census records no such holds and
no queued candidate. It does not mean there were no fires. “Incident report
details unavailable” means the counts, source-run interval or durable-health
binding could not be verified. Missing counts are unknown.

The reader checks the existing raw/qualified/excluded partition, held reasons,
optional admission count, truncation flag and source counters. It uses only the
unique matching saved source run. Older or contradictory details cannot explain
a newer health observation. Provider text is not used to infer a cause or copied
into the census explanation.

This display changes no collection, qualification, source status, candidate
budget, review, approval or sending behavior. NIFC incident sizes remain reported
sizes, with their original attribution and clocks; they are not measured burn
perimeters or independent corroboration of satellite detections.
