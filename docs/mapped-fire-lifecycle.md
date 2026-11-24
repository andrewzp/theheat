# Retained mapped-fire lifecycle

This local/preview workflow compares separately dated polygons from the NIFC
WFIGS Current Interagency Fire Perimeters view. It does not fetch source data,
enroll a production collector, run a model, approve publication or send to X.
The current incident-location/size-report collector remains a separate product.

The source contract uses the [NIFC polygon layer](https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0)
and [publisher item](https://www.arcgis.com/sharing/rest/content/items/d1c32af3212341869b3c810f1a215824).
`poly_PolygonDateTime` is the map capture time; creation, edit and retrieval clocks
cannot substitute. `poly_GISAcres` is acreage recorded on the polygon. It is
distinct from point-reported incident size and is not independently verified
ground area. The source's mapping-method text is retained without inventing an
instrument classification or accuracy. This mutable view drops records; an
absent later row is not evidence that a fire ended. Retaining an origin label
does not independently authenticate the publisher or establish reuse rights.

`FireEpisodeSession` requires the existing explicit local/preview PostgreSQL
repository. It retains exact response bytes with capture identity and digest,
then decodes them again on readback. Only public, approved, visible, undeleted
WF polygons with matching IRWIN incident IDs, a source polygon UUID, nonempty
source/method, explicit non-complex status and supported WGS84 rings qualify.
Truncated captures, unsupported topology and contradictory same-time maps hold.
Unknown UTC offsets and unsupported ArcGIS coordinate transforms are refused.
An immutable source-record ownership entry prevents a polygon record from being
reassigned to a different IRWIN incident, including across retained captures.

Incident identity, source polygon identity, map edition, editorial opportunity,
operation identity and publication receipt remain separate. An operation uses
an expected episode head and an episode transaction lock. An ambiguous commit
acknowledgement gets one read reconciliation, never another write or fetch.
Changing a label, ring start/order, retrieval clock or edit clock does not make
an opportunity. A newer map requires more than 5% change in source-recorded acres
and more than 5% change in signed-ring coordinate area, with distinct geometry,
to make another opportunity. The latter is a conservative map-change guard in
coordinate space; it is not a geodesic area measurement. Changed source/method,
late earlier maps and conflicting same-time maps require review instead.

`prepare_fire_request` resolves the current immutable head, reconstructs a compact
bundle, runs the real evidence audit, builds source-backed memory and prepares
the actual writer request. It rechecks the episode head and editorial policy
after assembly. Every retained member's capture and map time must precede the
explicit preparation clock. Relevant unresolved draft, ledger and memory attempts
fence preparation under the existing delivery rules, even with a numeric receipt.
The preparation result is not a dispatch grant:
`provider_transport=not_attempted`, `callback_enrollment=not_supported`.

Map history is reconstructed from retained qualified members. NIFC point reports,
FIRMS pixels, another IRWIN incident, unrecognized bindings and unknown deliveries
cannot supply it. Receipt-backed previous copy is only publication history.
Publication counts and `days_running` do not enter mapped-fire factual memory.
The writer must describe attributed, dated maps, without inferring actual fire
growth, continuous burning, duration, final burned area or cross-border impacts.
Large compact bundles fail the existing whole-bundle limit without truncation.

The existing NHC binding/context remains closed to its original cyclone schema.
The new mapped-fire family requires its own live resolver; a dictionary or a
miniature restored publication snapshot cannot certify fresh generation evidence.
The sealed graphics runtime refuses this family when no resolver is available.

Validation uses invented data in `tests/test_nifc_perimeter.py` and the new local
`tests/test_postgres_fire_episodes.py`. These fixtures establish software behavior,
not current weather, source availability, rights, writing quality, actual model
output, international coverage or publication. Heat, flood and the production
episode rollout remain separate work.
