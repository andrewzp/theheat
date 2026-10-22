# Source-backed MODIS delivery descriptions

The local review workflow supports one closed description derivation,
`modis_source_projection_v1`, for `modis_thermal_detection_map`. It reconstructs
facts from the independently validated retained specification. It does not
summarize, truncate, normalize, round source numbers, infer an incident, or change
the native five-file package. Other templates and historical `full_raw_alt`
records keep their original exact raw description behavior.

## Mandatory mapping

| Retained input | Exact description coverage |
| --- | --- |
| `synthetic` | Explicit synthetic/no-real-weather warning when true. |
| `source_product`, `satellite`, `instrument`, `acquired_at`, precision | NASA FIRMS MODIS_NRT, exact Terra/Aqua platform, MODIS, full reported UTC minute and explicit unknown measured seconds. Only the existing qualified MODIS source contract is accepted. |
| Every ordered `points` row | A primary, all remaining rows related, retained source order; every exact latitude/longitude in degrees and pixel FRP in MW. Existing round-trip numeric spelling is preserved, including zero and precision. |
| Every confidence and source version | If both fields are identical across **all** rows, one explicitly scoped “All confidence …, version …” statement applies to every row. Otherwise both exact fields appear in each row, with a corresponding table header. No value or version name is elided to fit. |
| Map palette, marker and scale semantics | Equal markers; blue-to-yellow linear FRP scale from zero to the exact source-derived axis maximum. A is the lead, never a maximum or severity selection. Labels are rounded; description row values are exact. |
| Scientific limits | Pixel-integrated radiative power, not temperature/area/whole-fire intensity. Centres are not flames, perimeters, footprints or separate-fire counts; scan/track/footprints are unknown. Same minute/platform does not prove a shared instant, overpass or incident. Confidence is source quality, with no incident/cause/impact/location certification. |
| Locator context | Plate carree, not distance/area; either omitted coastlines in a close-up or coarse land with inexact local boundaries. Dateline crossing is explicit when present. Inset means location/viewport, never fire area. Natural Earth 110m land4.1.0/public-domain attribution and absent-islands/not-proof-of-water qualification remain. |
| Acquisition/authority limits | Selected receipts only, without original HTTP/source authentication, freshness, review or publication approval. |

The full retained description additionally preserves methodology links, detailed
layout/rounding explanations, receipt/source spelling and original native-package
detail. Its raw terminal LF and original hash remain unchanged. Retaining that
full description does not waive any mandatory qualification in the wire text.

## Complete invented four-row example

This example is **998 Unicode scalars and 998 UTF-8 bytes**, with no terminal LF.
Its native raw description remains a separate longer artifact. All provider and
source inputs in the example are invented test fixtures.

```text
SYNTHETIC; not real weather. NASA FIRMS MODIS_NRT Terra/MODIS 2032-02-29T23:59:00Z (UTC minute, not seconds). Source order: A primary, others related. All confidence 91.0%, version synthetic-v1. Lat,lon degrees/FRP MW: A 35.0,-110.0/125.75; B 35.0,-109.989/500.1234; C 35.009,-110.0/750.25; D 35.009,-109.989/250.0. Equal markers; linear blue-yellow FRP 0-1000.0 MW; A lead, not max/severity. Rounded labels; exact rows. FRP=pixel-integrated radiative power, not temperature/area/whole-fire intensity. Centres not flames/perimeters/footprints/separate-fire counts; scan/track/footprints unknown. Same minute/platform: instant/overpass/incident unproven. Confidence=source quality; no incident/cause/impact/location certification. Plate carree, not distance/area. Coasts omitted in close-up. Inset=location/viewport, not fire area. Natural Earth110m land4.1.0 public domain; absent islands do not prove water. Selected receipts only; no original HTTP/source authentication/freshness/review/approval.
```

The one-row fixture is 922 bytes. Greater numeric precision, differing confidence or
version columns, Unicode versions, a dateline or coarse-land qualifier can exceed
the house bound. Such packages remain held: no field, qualifier, destination or
source row is removed to admit them. The conservative X guard still requires
both at most 1000 scalars and at most 1000 UTF-8 bytes; this is a local house rule,
not an asserted official byte limit. Actual PNG structure and all fixed selected
destinations still pass their existing independent checks before mutation.

## Version and lifecycle identities

The new description record is schema2 and retains exact wire text, its scalar and
byte counts/hash, raw and semantic alt hashes, source-input/spec/PNG identities,
proposal/packet/full draft-and-decision target, and policy/profile identities.
The existing schema3 joint review binds the exact record and its separate sixth
faithful-description confirmation. No checkbox supplies scientific authority.
The editor shows the exact currently reviewed record after successful independent
currentness checks; a prospective rereview record cannot replace its displayed
identity while current review/approval is shown.

Every new approval/lease/grant/before-call boundary reconstructs from the verified
server package. The SDK receives that exact wire string, and the verifier checks
both decoded text and immutable serialized request bytes. The new X-alt receipt
result has explicit schema2, `raw_alt_sha256`, `wire_alt_sha256` and
`platform_description_sha256` fields. Historical unversioned results retain their
original raw `alt_sha256` semantics. The retained delivery intent stays schema2;
its nested description version distinguishes the new derivation.

New history content is schema2 only for this derivation. It displays earlier
reviewed wire text separately from complete raw alt, while stage receipts alone
establish attempted/confirmed/unknown outcomes. An intent does not establish that
text was sent. Existing schema1 history and original receipt/reconciliation/restore
semantics remain available without a current profile/fit/native/source-availability
lookup. Editing, stale sources, changed policy/profile/native inputs or revoked
roles cannot resurrect old review or approval by selecting back.

The destination set remains X and Bluesky. A local loopback success does not
qualify a live API or source truth, remove an unresolved destination obligation,
authorize publication, or complete broader graphics/scientific/human acceptance.
