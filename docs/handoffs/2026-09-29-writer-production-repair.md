# Focused writer request repair

The writer's structured-output schema was rejected before generation because its
nullable enum combined an enum with a string/null type array. Repeating the same
HTTP400 cannot repair that request. The schema now expresses the same exact values
as anyOf string-enum/null branches; fields remain required and additional properties
remain forbidden. Parser semantics and runtime model/prompt/sample settings stay
unchanged. Anthropic documents anyOf and null in its [schema support](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

The shared retry owner reads structured SDK or HTTP statuses. Definite 4xx stop
once, except retryable 408/409/429. Billing retains its distinct error. Unknown,
server and transport failures keep the existing bounded budget. Exceptions remain
the originals; no provider fallback or new error-body logging is introduced.

Core requirements pin Anthropic 1.9.0, Google genai 2.25.0, HTTPX 0.28.1, HTTPX2
2.13.1 and Pydantic 2.13.5. Those current SDK generations are installed together in
a clean test environment. This bounds core provider upgrades, not every Python
transitive dependency. Future upgrades require wire tests and required CI.

The actual Anthropic SDK is exercised with an offline HTTP fixture reproducing
the observed schema rejection. It verifies one failed request, compatible encoding,
strict output values and exact user content. This fixture is not the live compiler;
provider acceptance and funded generation remain unobserved until release.

No batch feature, experimental database authority, model/sample change, paid trial,
credit change, publication activation or public correction is included. The policy
manifest change invalidates obsolete approvals and needs manual dashboard deployment
after required CI at the reviewed head. Automatic publication stays paused.

Local validation: 3,795 offline Python tests passed with 41 paid tests excluded;
49 focused writer/retry tests and all 28 place tests passed. Ruff, mypy over 139
source files, both generated contracts, 294 dashboard tests and the locked
Next.js 15.5.25 production build passed. Python was 3.14.3 and Node was 25.8.2;
remote Python 3.12 / Node 24 CI is still required. Three dependency deprecation
warnings remain. A clean environment installed the complete requirements with
no broken dependencies; the saved checkout's environment was not modified.

The first full run reproduced an unrelated calendar-sensitive historical-place
fixture: its September 8 forecast was compared with an archive ending today.
The fixture now uses that same fixed date for its archive. Production scientific
cutoffs were unchanged. Current-model review found no changes to workflow,
publishing, configuration or prompt files. This is local verification, not an
independent review, a deployment, or measured cost/quality improvement.
