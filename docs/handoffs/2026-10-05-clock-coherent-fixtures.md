# Clock-coherent canary fixtures

Forward-clock checks exposed inconsistent fixture clocks across processes. The
Python test clock shifts, but shell `date` and Node's default clock do not. A third
fixture manufactured a later event by replacing a hard-coded year, which stopped
producing a different event when the clock reached that year.

The heartbeat test still executes the actual workflow shell body. An offline date
executable supplies the same shifted timestamp as the Python observer, and the test
asserts that the captured beacon carries it. The usage roundtrip still persists
through both storage implementations and preserves receipts and unknown charges;
Python and JavaScript now receive one explicit reporting period from the recorded
usage day. Place-identity tests use their observation dates and derive a distinct
future date without assuming the current year.

An additional adverse file-order run reproduced leaked mocks on unchanged code:
the legacy facade copies patched globals into source modules, outside monkeypatch's
direct restoration targets. A test-local fixture now restores those copied bindings.
The scientific source tests retain their real qualification and clustering asserts.

These are test-fixture changes. Production clocks, source freshness limits, billing
calculations, scientific gates and publication controls are unchanged. The full
offline suite and exact-head required CI remain release gates; successful test
execution is not evidence of live source recovery or editorial improvement.
