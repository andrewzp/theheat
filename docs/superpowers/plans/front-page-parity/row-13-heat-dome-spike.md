# Row 13 — Heat-dome / population-exposure class: the design spike (read-only)

> **Protocol, not a build plan.** Timebox: one session. Deliverable: a go/no-go with a
> design sketch, appended to THIS file under "Findings". No code ships from the spike.
> Any session (or a lesser model) can run it — every step is read-only investigation.

**The story class we can't see:** "200M+ Americans under extreme-heat alerts" led the
world's front page the first week of July 2026; the bot had no path to it. Every heat
signal is a point/sampled-city metric; nothing aggregates ALERT EXTENT × POPULATION.

## Questions the spike must answer (with evidence links pasted into Findings)

1. **US half — does the NWS alerts feed carry enough?** The bot already fetches
   `api.weather.gov/alerts/active` (`src/data/nws_alerts.py`; currently a 9-type
   allow-list including Extreme Heat Warning). Answer from the live API + docs:
   (a) do alert objects carry affected-zone IDs (`geocode`/`UGC`/`affectedZones`)?
   (b) is there a static, downloadable zone→population table (NWS zone shapefiles ×
   census; or does the CAP payload itself carry population)? (c) what would "N million
   under Extreme Heat Warning/Watch" cost to compute per cycle — fetch size, zone
   count, a cached zone-population file's size?
2. **Honesty shape:** is the claim "N million people were under extreme-heat warnings"
   constructable from feed facts alone (zone populations summed), and what are the
   double-counting traps (overlapping zones, Watch vs Warning, marine zones)? What
   precision is honest (round to the nearest 10M)?
3. **World half — is there any equivalent?** MeteoAlarm (Europe) awareness levels;
   anything machine-readable elsewhere? If the world half is thin, is a US-only class
   acceptable given the coverage-watch will flag mono-country patterns (it watches
   heat already) — or does US-only violate the global-coverage bar? (Note: reganom
   already covers the world's regional-heat story; the exposure class may honestly be
   US-first the way `fire_footprint` is, with the world half via row 10's feeds.)
4. **Threshold shape:** what makes an exposure reading EXTRAORDINARY vs routine
   summer? (Sketch: a floor like ≥50M under Warning-tier, or a percentile vs a rolling
   baseline the state would keep — which needs state design.) One draft per event-peak,
   dedup like tier crossings?
5. **Overlap check:** does this duplicate `severe_weather` (which already passes
   Extreme Heat Warning through per-alert, threshold 58)? The new class is the
   AGGREGATE story; confirm the dedup story between one mega-alert draft and many
   per-alert drafts.

## Method

- Read `src/data/nws_alerts.py` + one live `curl` of the active-alerts API with an
  Extreme Heat filter; paste a trimmed sample alert JSON into Findings.
- WebSearch/WebFetch for the zone-population dataset question (NWS public zone
  shapefiles; census gridded population; any ready-made zone-pop CSV) — cite exact
  URLs and licenses.
- Write the go/no-go: GO requires (1) zone→population resolvable from static public
  data ≤ a few MB cached, (2) the honest claim constructable per §2, (3) a defensible
  extraordinariness floor per §4. NO-GO or DEFER otherwise, with the specific blocker
  named.

## Findings

*(empty — the spike session appends here)*
