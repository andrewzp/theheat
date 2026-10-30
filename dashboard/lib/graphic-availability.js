// W10.6: what each post-image family needs and what is missing here, for the graphic picker
// and Operations. Display only: the Python preview, the drafts route and the sender remain
// the authority, and nothing here probes a store, a database or a host. A configured store is
// reported as configuration, never as proven access, hosted acceptance or native rendering.

export const MEDIA_STORE_ENV = "THEHEAT_MEDIA_STORE", MEDIA_STORE_DSN_ENV = "THEHEAT_MEDIA_STORE_DSN"

export const GRAPHIC_FAMILIES = Object.freeze([
  { family: "temperature", kind: "gist_temperature_comparator_v1", label: "Station temperature comparator", lane: "native",
    needs: ["the qualified observed GHCN station comparator saved with the draft"] },
  { family: "pm25", kind: "gist_pm25_forecast_v1", label: "PM2.5 model forecast", lane: "native",
    needs: ["an unextended single-source CAMS (via Open-Meteo) hourly forecast saved with the draft"] },
  { family: "modis", kind: "gist_modis_locator_v1", label: "MODIS fire locator", lane: "native",
    needs: ["1–4 receipt-bound MODIS_NRT detections saved with the draft"] },
  { family: "viirs", kind: "gist_viirs_locator_v1", label: "VIIRS fire locator", lane: "native",
    needs: ["1–4 receipt-bound NOAA-20 or NOAA-21 VIIRS detections saved with the draft"] },
  { family: "hot10", kind: "gist_hot10_bulletin_v1", label: "Hot 10 departure table", lane: "native",
    needs: ["a qualified Hot 10 bulletin with point monthly normals saved with the draft"] },
  { family: "crw", kind: "gist_crw_anomaly_v1", label: "NOAA CRW sea-surface anomaly", lane: "retained",
    needs: ["a qualified primary NOAA CRW regional anomaly saved with the draft",
      "its exact retained CSV/metadata packet (collector retention is off by default)", "a read-only media store"] },
  { family: "radar", kind: "gist_published_radar_v1", label: "Published NWS KTLX radar frame", lane: "published",
    needs: ["a catastrophic NWS Tornado Warning with its full retained alert",
      "a retained KTLX Local Standard frame with its product and reuse references", "a read-only media store",
      "three human attestations at joint review (delegated review does not cover published images)"] },
  { family: "cone", kind: "gist_published_chart_v1", label: "Published NHC forecast cone", lane: "published",
    needs: ["an NHC advisory draft",
      "a retained NHC track-forecast cone for the same storm and advisory with its product and reuse references",
      "a read-only media store",
      "three human attestations at joint review (delegated review does not cover published images)"] },
])

// Presence and backend name only; never a path, DSN, host or credential value.
export function mediaStoreSetting(env = process.env) {
  const value = typeof env?.[MEDIA_STORE_ENV] === "string" ? env[MEDIA_STORE_ENV].trim() : ""
  if (!value) return { configured: false, backend: null, reader_credential: "not_required" }
  if (value === "postgres") return { configured: !!env[MEDIA_STORE_DSN_ENV], backend: "postgres",
    reader_credential: env[MEDIA_STORE_DSN_ENV] ? "present" : "missing" }
  if (/^sqlite:\//.test(value)) return { configured: true, backend: "sqlite", reader_credential: "not_required" }
  return { configured: false, backend: "unsupported", reader_credential: "not_required" }
}

function missingStore(store) {
  if (!store) return "the media store configuration is not reported here"
  if (store.configured) return null
  if (store.backend === "postgres") return `the read-only media store credential (${MEDIA_STORE_DSN_ENV})`
  if (store.backend === "unsupported") return `a supported media store setting (${MEDIA_STORE_ENV} is unsupported)`
  return `a read-only media store (${MEDIA_STORE_ENV})`
}

// One row per family for Operations: requirement, lane and the input missing on this deployment.
export function graphicFamilyAvailability(store) {
  return GRAPHIC_FAMILIES.map(row => {
    const missing = row.lane === "native" ? null : missingStore(store)
    return { family: row.family, kind: row.kind, label: row.label, lane: row.lane, needs: [...row.needs],
      status: row.lane === "native" ? "from_saved_source" : missing ? "missing_input" : "store_configured_unverified",
      missing }
  })
}

export function graphicAvailabilityPayload(env = process.env) {
  const store = mediaStoreSetting(env)
  return { store, families: graphicFamilyAvailability(store) }
}

// The picker line for one draft's family: what it needs and the first missing input named.
export function draftGraphicRequirement(family, draft, store, retainedPacket = null) {
  const row = GRAPHIC_FAMILIES.find(item => item.family === family)
  if (!row) return null
  const missing = []
  if (row.lane !== "native") {
    const absent = missingStore(store)
    if (absent) missing.push(absent)
    if (row.family === "crw" && (!retainedPacket || retainedPacket.invalid))
      missing.push(retainedPacket?.invalid ? "a valid retained packet reference (this draft's reference is malformed)"
        : "this draft's retained CRW packet identity (paste it below if it was retained locally)")
    if (row.lane === "published" && !draft?.media_attachment)
      missing.push("the retained published asset identity (paste it below after local retention)")
  }
  return { family: row.family, label: row.label, lane: row.lane, needs: [...row.needs], missing }
}

export const LANE_TEXT = { native: "rebuilt from the saved source; no store needed",
  retained: "rebuilt from one retained source packet in the media store", published: "an unaltered published image retained in the media store" }
