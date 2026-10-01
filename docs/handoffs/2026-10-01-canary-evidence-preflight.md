# Canary evidence preflight

The positive writer canary used three packets explicitly labeled invented and
nonpublishable. A correct refusal was followed by another sampling round, then
reported as a degraded writer. That test could neither prove source truth nor
reliably distinguish a provider outage from an appropriate editorial rejection.

Preflight now rejects those packets before every provider and safety call, with
`monitor_blocked / fixture_ineligible`, unobserved provider/schema and unknown
writer quality. A blocked test remains a failure, not a green skip. Current fixture
labels are preserved. An empty code-reviewed qualification registry deliberately
keeps all current positive fixtures unqualified; removing labels is insufficient.
A future entry must bind the exact packet and evidence review, with aware source
and expiry times and at most a 24-hour window. Scientific review must independently
justify the packet, permitted claim and window; a hash does not prove truth.

The existing two-of-three positive threshold and mandatory safety behavior remain.
Sampling diagnostics distinguish invalid schema, clean refusal, a recorded budget
exception, unclassified call failure and unpassed safety. Error bodies and generated
text are omitted from these diagnostic messages. An unavailable check is not called
an affirmative scientific rejection or a pass.

Offline tests call the actual marked entry point with provider/safety traps: the
current three packets make zero requests, compared with six stubbed requests in
the previous two-round failure path. Injected qualification/response controls also
verify exact identity, expiry, the unchanged positive threshold, missing credentials,
malformed output and safety failure. These controls do not qualify real sources or
evaluate model quality. No paid test is needed for this change.

The scheduled and weekly triggers, PR replay opt-in and required offline CI are
unchanged. This repair stops a known waste mechanism; it leaves positive monitoring
visibly blocked. A complete read-only monitor still needs exact ordinary-run joins
between provider response, candidate, evidence and every required check. Existing
usage observations and saved draft counts alone cannot supply that proof. There is
no measured invoice saving, restored-provider claim or publishing activation.
