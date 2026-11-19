# Inland satellite precipitation discovery

When the existing observed GPM report lane is enabled, a successful daily IMERG
Late full-grid download also supplies inland discovery. The collector shares the
download and decoded precipitation array with city sampling. It makes no
additional discovery GET and has no new activation flag. Point-only fallback
cannot qualify this grid evidence. Existing city reports remain supported.

The offline-generated mask contains 6,127 one-degree tiles in 77 cartographic
regions between 60°S and 60°N. Each tile and a 0.5° angular margin must be strictly
inside one eligible Natural Earth polygon. This margin is not an accuracy claim.
Borders, coasts, holes, overlaps, disputed classifications and unsupported labels
are excluded. These are map labels, not a certification of administrative borders
or a global weather-coverage denominator. See `data/geography/NOTICE.json` for the
pinned public-domain source, hashes and license.

Every successful qualified frame examines the 100 cells in each supported tile.
It chooses one eligible cell per tile by estimated depth, with a fixed cell-index
tie break. Qualification requires canonical 0.1° axes, matching Gregorian CF day,
daily units and all 48 valid half-hour slots. The operating range is 150–1,000
mm/day, with a completed-day end no older than 36 hours. The range is an editorial
filter, not a record, physical ceiling or independent measurement. Exclusions are
counted separately; missing or unexamined cells are never treated as zero.

At most three reports share the existing city-report slate. Only one routine
writer candidate and one sample can be paid for, and a paid failure receives no
refill. A report states one cell's satellite estimate of daily water-equivalent
precipitation, its regional context, date and NASA citation. It cannot assert a
country total, area maximum, rain/snow phase, gauge measurement, historical record,
storm identity or impact. Distinct cells are not automatically distinct storms.

The compact packet retains the selected cell, value, valid-slot count, source
time/units/day, source-file SHA-256 and pinned geography identity. The full raw
grid is not archived by this lane. Each existing live source boundary fetches the
same source day and requires exact retained-proof agreement; the file digest
changing holds the story even if its numeric value is unchanged. Required model
checks, approval binding, publication epoch, send intent and unknown-send rules
continue to apply. Same-cell/product/day duplicates use retained coordinates
across city and grid schemas. No historical point is inferred from a new label.

`details.rainfall_grid_discovery` records the finite scan and exclusion counts.
The algorithm revisits every supported tile on each successful qualified frame;
this is not a wall-clock freshness, source-access or scheduler guarantee. Existing
retrieval walkbacks, retries and point-fallback caps remain. Physical requests,
helper invocations and unknown provider costs are different quantities. Sharing
a grid is not a zero-cost, invoice or monthly-budget guarantee.

The separate, default-off regional point fallback now qualifies and orders its
watchlist before deriving checkpoint identities. Reordering CSV rows or changing
numeric formatting preserves the cursor; a genuine population change starts a
new region set. Its flag and 75-point remote cap are unchanged.

Regenerate the pinned geography offline with
`python scripts/gen_imerg_country_tiles.py`; verify with `--check`. The generated
check is part of core CI. Source inventory, editorial policy and graphic runtime
must then be generated in that order. The sealed runtime includes the pure cell
contract and derived geography only; HDF5, NumPy and live collectors stay outside.
