# Check the final cyclone text before saving it

Cyclone dispatch previously appended an advisory URL after the writer pipeline's
checks and ran safety again. A shortened display link could remain beside the full
URL, and the edited text correctly lost its earlier review binding.

The synchronous pipeline now formats each viable candidate before slate selection
and mandatory checks. Optional revisions and shadow drafts use the same pure
formatter. Copies preserve the original writer result. Check inputs, returned text,
retained factual rejections and the final reviewed-text hash refer to that candidate.
Dispatch refuses a result that still needs formatting, or has a mismatched cyclone
kind, without editing it or buying another safety check.

The formatter applies only to the four previously supported cyclone kinds. A single
unambiguous advisory URL can be appended within both existing length limits. Exact
complete whitespace-delimited URLs prevent duplicate appends. Only a terminal
abbreviation with a matching hostname and literal nonempty path prefix is replaced;
uncertain links, source queries, case/encoding differences, interior links and prose
remain intact. A replacement that cannot fit leaves the original text untouched.
Missing, malformed or conflicting source values confer no formatting authority.
The formatter does not shorten scientific claims or certify source truth.

The formatter and dispatch code join the editorial policy identity. Runtime models,
prompts, routine samples, revision flags and retry limits are unchanged. This adds
no model call and removes the dispatch-only repeat safety call. Offline tests use
invented copy and explicit model stubs; they prove binding and routing, not improved
human preference, lower invoices or factual qualification of real weather claims.

Default-OFF batch results retain their original parsed candidate IDs and packet
schemas. Derived final-text identity at batch check intake is a separate outstanding
integration contract before activation. No historical text, production storage,
publishing control or public correction is changed by this release.
