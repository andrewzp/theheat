# Tropical Cyclone Feed Investigation

Date: 2026-05-15

Lane 09 requires NHC and JTWC operational cyclone feeds. The live source check
found:

- NHC `https://www.nhc.noaa.gov/CurrentStorms.json` is reachable and currently
  returns `{"activeStorms": []}`. The parser therefore treats an empty
  `activeStorms` list as a clean success.
- JTWC `https://www.metoc.navy.mil/jtwc/rss/jtwc.rss?layout=enhanced` is
  reachable and returns RSS. During this check it contained a "No Active
  Tropical Warnings" item plus significant-weather advisory links.
- JTWC `https://www.metoc.navy.mil/jtwc/products/atcf/` returned HTTP 403 even
  with a bot user-agent. The implementation does not depend on directory
  listing. It follows warning/product links exposed by the RSS feed instead.

Implementation implication: NHC and JTWC fetchers must both treat "no active
storms/warnings" as success with zero observed advisories, and JTWC must not
require ATCF directory-list access.
