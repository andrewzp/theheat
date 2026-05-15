# Copernicus EMS Flood Feed Investigation

Checked: 2026-05-15 02:43 UTC

Lane 12 requires a live source check before implementation. The current
Copernicus EMS Mapping site differs from the lane brief:

- `https://emergency.copernicus.eu/api/v1/activations/?event_type=flood`
  returns HTTP 404 with an HTML "Page not found" body.
- `https://emergency.copernicus.eu/mapping/list-of-activations-rapid`
  redirects to a trailing-slash URL and then returns HTTP 404.
- The current official harvesting docs point to
  `https://mapping.emergency.copernicus.eu/activations/api/activations/` for
  the consolidated Mapping API, and to
  `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/`
  for Rapid Mapping public activation summaries.

Live Rapid Mapping summary curl:

```sh
curl -sS -L \
  'https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/?limit=5&category=Flood'
```

Current summary schema:

```json
{
  "count": 86,
  "next": "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/?category=Flood&limit=5&offset=5",
  "previous": null,
  "results": [
    {
      "code": "EMSR871",
      "countries": ["Italy"],
      "eventTime": "2026-03-31T15:00:00",
      "name": "Flood in Abruzzo, Molise and Basilicata regions, Italy",
      "centroid": "POINT (14.938764359319357 41.899617109537935)",
      "activationTime": "2026-04-01T15:16:00",
      "category": "Flood",
      "lastUpdate": "2026-04-14T07:32:28.491219",
      "closed": true,
      "gdacsId": null,
      "n_aois": 1,
      "n_products": 2
    }
  ]
}
```

Live Rapid Mapping detail curl:

```sh
curl -sS -L \
  'https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR871'
```

Current detail schema adds `subCategory`, `reason`, `reportLink`, `continent`,
country objects, `aois`, product metadata, and top-level `stats`. Flood impact
metrics are exposed as:

- `stats["Population [No.]"]` for affected population.
- `stats["max_extent"]` in hectares for maximum mapped flood extent.
- AOI/product stats such as `Flooded area`, `Maximum of all extents**`, and
  `Estimated population`.

Implementation implication:

- Use the Rapid Mapping summary endpoint with `category=Flood` as the primary
  listing source.
- Fetch details per activation to extract top-level impact stats and canonical
  country names.
- Treat an empty `closed=false` flood query as a clean success. On this check it
  returned `count: 0`.
- The current public API does not expose the brief's `severity_tier`; the
  implementation derives severity from mapped impact (`Population [No.]` and
  mapped flood extent) and preserves tier-dedup semantics in state.
