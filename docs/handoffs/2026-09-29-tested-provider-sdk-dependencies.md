# Tested provider SDK dependencies

The previous requirements allowed unreviewed major SDK upgrades at install time.
The local Anthropic 0.94/Google genai 1.71 environment differed from observed
production Anthropic 1.9/Google genai 2.25. In a focused isolated reproduction,
32 transport checks failed because the newer Anthropic SDK requires httpx2 clients;
158 checks passed. This is preserved as failed evidence, not relabeled as success.

## Change

Core requirements now pin Anthropic 1.9.0, google-genai 2.25.0, httpx 0.28.1,
httpx2 2.13.1 and pydantic 2.13.5. Update them through reviewed dependency changes
and actual-SDK wire checks. This is a provider-contract lock, not a complete lock
of every dependency or a guarantee across all platforms. Runtime model IDs,
prompts, samples and billing settings are unchanged.

The batch adapter selects the family of the SDK's public DefaultHttpxClient.
It supports the verified old httpx family and new httpx2 family, regardless of
whether both modules happen to be installed. It refuses unknown families before
provider access. No private SDK attribute, version cutoff, redirect, retry or
provider fallback is introduced. Mocked HTTP tests use the SDK's actual family,
so client construction and raw request/response behavior remain exercised.

## Evidence

Six new family-selection cases plus the existing provider boundary regressions
pass: 196 focused checks in each SDK generation. This includes the repaired writer
schema, permanent/retryable errors, batch submission, bounded result reads, late
responses, redirects, response cleanup, safety and news call bounds. Network
barriers remain active and no paid provider request occurred.

All 4,522 offline Python tests pass in the clean pinned environment, with 41 paid
tests excluded. Ruff, mypy over 151 source files, both generated contracts and
diff checks pass. Three SDK/NumPy deprecation warnings remain. The unchanged
dashboard policy manifest already passed 294 tests and the Next.js 15.5.25 build
in the preceding schema slice. No duplicate browser/visual QA is claimed.

A clean isolated environment was installed from the complete requirements, rather
than overlaying new SDK dependencies on an older social-client environment. Its
pip check reports no broken requirements. The saved checkout's virtual environment
was not modified. The first overlay's dependency conflict and test failures are
retained privately as diagnostic evidence.

Required remote CI still uses Python 3.12; these local environments use Python
3.14.3. Live provider acceptance, source recovery, batch activation and measured
cost/quality improvement remain separate gates. Read the current implementation
checkpoint before release; publishing remains paused.
