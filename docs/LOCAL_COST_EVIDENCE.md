# Cost evidence in the local editor

The experimental PostgreSQL editor adds a local request view to the dashboard's existing cost card. It shows reserved allowances and retained usage for writing and required checks. These records do not establish the final provider bill or complete production spending. The production Gist view and its existing estimates remain separate.

The view reads the same request, reservation, grant and response records used by the local workflow. It creates no second spending ledger, runs no model or source request, and does not settle or release a reservation. Editing a draft, rejecting a response or allowing its evidence to expire does not erase the request's incurred usage or turn an unknown charge into zero.

## Reading the amounts

- Reserved allowance and daily/monthly commitments are local reservation amounts, not billed charges.
- A recorded settlement describes an existing journal entry. It is not an independently reconciled invoice.
- Token counts come from a complete retained response and its original observation time. Missing, invalid, incomplete or conflicting usage stays unavailable.
- The local commitments must not be added to the separate legacy estimates displayed above them.

Amounts use integer microdollars through storage and transfer, with exact decimal display. The view does not invent prices for missing usage, cache discounts, hosting, data, platform, repair or other unrecorded costs. It does not assert a production spending cap or measured savings.

## Bounded detail and failures

The view shows at most20 requests, prioritizing unresolved reservations. Summary amounts use the existing database constraints and aggregates; detailed hash and relationship verification applies only to the selected requests. This is explicitly not a cryptographic audit of the entire journal. Omitted rows remain in the summary and are counted as omitted.

Usage is read from bounded retained bytes after the database connection closes. It is not derived by rerunning a writer verdict, source qualification, image decoder or current approval check. The fixed usage-parser version identifies how the displayed usage was extracted; it does not certify provider billing.

Missing configuration, invalid evidence, excessive size or a read deadline produces an unavailable cost view while leaving the draft workflow usable. Existing authentication and local preview isolation still apply. Restart and restore tests use invented requests and responses; deployment, browser usability and actual bills require separate verification.
