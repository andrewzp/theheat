# P08 prompt follow-up: explicit rejection metadata

This is a separate follow-up to P07 core commit `519396d33ef6dd0a7b15dcc3c87051ed08b988ce`. Integrate it **atomically with P08's matching writer schema/parser**. The P07 core remains independently shippable with its seven-field output.

The same writer response now requests nullable `kill_scope` and `kill_code`; no model stage, extra call or reasoning pass is added:

- A viable tweet has null scope and code.
- `evidence` means specifically inadequate/missing source evidence or conflicting evidence; the permitted code is `insufficient_evidence` or `conflicting_evidence`.
- `style` covers weak significance, wording and length; `context` covers repetition, coverage and memory; `unknown` covers unclear classification. These scopes require null code.
- An uninteresting but supported fact is not called missing evidence. Metadata describes the model's own rejection; it is not independent proof of a scientific defect.

P08 owns strict local validation, two matching eligible rejections, version/context keys and bounded TTL. No cache becomes safe merely because the prompt asks for these fields. Older/missing/malformed labels must remain non-cacheable. Changed evidence and actual prompt/model/policy/relevant-memory changes must escape a cached rejection.

Validation here covers prompt shape and mocked request wiring only: all 34 prompt tests and Ruff pass. The writer system is now 10,340 characters (486 more than P07 core), within the existing 10,500-character review budget. This is not a measured billing change. P08 must run its schema/parser/cache tests after integration. Do not infer eligibility from arbitrary `kill_reason` wording or from this prompt-only test. No paid model request or production change was made.
