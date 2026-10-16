# One-shot fresh sample trial

This is an opt-in generation test while the recurring bot remains paused. It does
not publish, write production state, approve drafts, enable schedules, or establish
a monthly spending cap. Obtain explicit operator approval before dispatching it.

The initial source is the existing official NWS rare-warning lane. It prepares up
to two current candidates, at most one per warning kind, using the existing source
parser, scoring, evidence contract and writer/check pipeline. Issuance must be
within six hours and the warning must remain valid immediately before generation.
Fewer or zero candidates is a valid result; it never searches for replacements.
Human review is still required for factual accuracy, importance and writing quality.

## Enforced limits

- Two preselected candidates, one writer sample each, critic enabled, no revision
  or refill. Required safety, deterministic honesty, factual and editorial checks
  remain mandatory; an unavailable check never passes.
- One paid dispatch per candidate/stage: writer, safety, factual check and critic.
  Eight maximum paid dispatches. An internal semantic/transport retry is refused
  before another dispatch; Google SDK retry attempts are one, Anthropic retries zero.
- Each serialized request and actual SDK HTTP body is at most128KiB. Trial-only
  HTTP hooks journal before sending, fence a second physical send per reservation,
  and disable redirects for both providers. Maximum output tokens: writer1024,
  safety2048, factual checker8192, critic8192. Google output includes thinking.
- Only the trial's explicit priced model profile is allowed: Sonnet4.6 writer,
  Gemini2.5Flash safety/factual and Gemini2.5Pro critic. This pins the safety alias
  for the trial; it does not change normal production model settings or prompts.
- Reservations are fsynced before dispatch and never refunded automatically.
  Transport uncertainty, journal failure, exceeded limits or an attempted retry
  stops further purchases. A `STOP` file in the packet prevents the next request;
  it cannot recall an already submitted request.
- Local execution exclusively claims the approved packet. The GitHub workflow is
  serialized, requires explicit approval text and production pause, refuses all
  run attempts after the first, and checks durable run metadata so a second dispatch
  with the same trial ID cannot purchase again. Unknown outcome requires review,
  never a workflow rerun or a new trial ID without new approval.

## Cost interpretation

The process refuses another dispatch when its **conservative token-cost scenario**
would exceed$2. Each call reserves the full128KiB wire allowance at one byte per
input token, including the envelope/schema, full configured output, no free tier or cache savings, and
five-minute cache-write pricing for every Sonnet input token. It is deliberately
conservative but is not exact provider token counting or an invoice guarantee.
Hard call/byte/output bounds are separate from that estimate. Unknown charges stay
reserved; returned token usage is saved but not treated as a reconciled bill.

Rates checked15October2026: [Anthropic standard pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[Google standard pricing](https://ai.google.dev/gemini-api/docs/pricing). The scenario
excludes taxes, other account usage, hosting and development-model usage. It does
not enforce the regular bot's monthly budget. Final posting's safety call and the
real post require a separate proposal and authorization.

## Operator procedure

1. Review the released code/CI and the finite proposal. Create a unique32-character
   lowercase hexadecimal trial ID and a local private encryption key/certificate.
   Keep the private key outside Git. The workflow receives only the public PEM.
2. Obtain approval for that trial ID, code revision, source/model profile and
   limits. Do not enable the regular paid-evaluation or collection switches.
3. Manually dispatch `fresh-sample-trial.yml` with the approved ID, exact released
   commit SHA, public certificate and literal `APPROVE-2-USD-SAMPLE-TRIAL`. Changed
   code or an invalid/expiring encryption recipient blocks before purchases. This declaration is a
   deliberate operator action, not authentication or standing paid authorization.
4. Inspect the existing run, not a rerun. Its safe log contains reservation
   ordinals/stages/outcomes, never exact source/history/draft text. Results are
   encrypted on the runner before artifact upload and retained for three days.
   A failure before encryption may leave no usable artifact; cost/outcome remain
   unknown, and the same trial ID still cannot run again.
5. Download the `.cms` artifact through the normal authenticated GitHub route,
   decrypt with the locally held key, and review source, checks, draft and returned
   usage privately. Never commit plaintext packets or historical state. A passing
   model verdict is not independent scientific or human quality acceptance.

Local preparation uses `scripts/fresh_sample_trial.py prepare --state <private
snapshot> --output <new-private-directory>` without paid calls. Local execution
additionally requires configured provider credentials and the separately approved
packet SHA256; expired, relocated or altered packets refuse execution. The GitHub
workflow uses its existing secrets and prepares/executes a fresh one-hour packet
within the explicitly approved one-shot scope. That workflow approval covers fresh
selection and generation under the specified limits; its internal packet SHA is
an integrity check, not a claim of a second human approval of the selected packet.
No secret needs to be copied locally.

The three older manual evaluation workflows now require both production pause off
and explicit paid-evaluation opt-in before any step. Leave them off for this trial.
