"use client"

import React, { useEffect, useRef, useState } from "react"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, firePreviewSourceStatus, graphicRequest, graphicRequestKey, hot10PreviewSourceStatus,
  isTemperaturePreviewType, mediaPNGRequest, retainedPacketReference, storeFamilyFor, temperaturePNGRequest,
  temperaturePreviewSourceStatus } from "../../lib/graphic-preview.js"
import { LANE_TEXT, draftGraphicRequirement } from "../../lib/graphic-availability.js"
import { textGraphicAgreement } from "../../lib/text-graphic-agreement.js"

const h = React.createElement

function PostingWindow({ window }) {
  return window.status === "current"
    ? h("p", { className: "graphic-posting-window" },
      `Within its posting window when previewed (${window.checked_at.slice(0, 16).replace("T", " ")} UTC). Approval and sending check the source time again.`)
    : h("p", { className: "graphic-posting-window", role: "note" },
      `Not postable now: ${window.reason}. This historical preview stays available to inspect; approval and sending will refuse it.`)
}

// The inline card image is ~244 px wide on a 320 px phone. This opens the same
// reviewed bytes at the full viewport width; Escape or the close button returns
// focus to the opener.
export function FullSizeImage({ url, alt, title, width = 1200, height = 1500 }) {
  const dialog = useRef(null), opener = useRef(null), closer = useRef(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const node = dialog.current
    if (!node) return undefined
    // Escape and the close button both end here: one place restores focus.
    const closed = () => { setOpen(false); opener.current?.focus() }
    node.addEventListener("close", closed)
    return () => { node.removeEventListener("close", closed); if (node.open) node.close() }
  }, [])
  const show = () => {
    const node = dialog.current
    if (!node || node.open) return
    setOpen(true)
    node.showModal()
    closer.current?.focus()
  }
  return h(React.Fragment, null,
    h("button", { type: "button", className: "btn sm graphic-full-size-open", ref: opener, "aria-haspopup": "dialog",
      onClick: show }, "View full size"),
    h("dialog", { ref: dialog, className: "graphic-full-size", "aria-label": `Full-size image: ${title}` },
      h("button", { type: "button", className: "btn sm", ref: closer, onClick: () => dialog.current?.close() }, "Close full-size image"),
      open && h("img", { src: url, alt, width, height })))
}

function PublishedFigure({ value, url, originalURL }) {
  const info = value.inspection
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.delivery_text, width: value.width, height: value.height }),
    h(FullSizeImage, { url, alt: value.delivery_text, title: value.title, width: value.width, height: value.height }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", { className: "graphic-kind" }, `${info.label} · published original, not a TheHeat chart`),
      h("p", null, `${info.attribution} · ${info.time_literal}`),
      h("p", null, `Quantity: ${info.quantity}. ${info.context}`),
      h("p", null, `Legend: ${info.legend.join(" · ")}`),
      h("p", null, `Retrieved ${info.retrieved_at.slice(0, 16).replace("T", " ")} UTC from ${info.source_url} (stored copy; nothing is fetched now).`),
      h("p", null, `Reuse basis: ${info.reuse_url}. Product definition: ${info.product_reference_url}. Credit kept; no endorsement implied.`),
      h(PostingWindow, { window: value.posting_window }),
      h("div", { className: "graphic-full-description" }, h("strong", null, "Image description sent to X"), h("p", null, value.delivery_text)),
      h("details", null, h("summary", null, "Original as retained (exact bytes, inspection only)"),
        originalURL && h("img", { src: originalURL, alt: `Retained original: ${value.title}`, width: value.width, height: value.height }),
        h("p", null, "X receives the pixel-equivalent PNG above; the original stays retained unchanged.")),
      h("details", null, h("summary", null, "Expanded source details (not sent)"), h("p", { style: { whiteSpace: "pre-wrap" } }, value.expanded_description))))
}

const signedC = value => `${value > 0 ? "+" : value < 0 ? "\u2212" : "+"}${Math.abs(value).toFixed(1)} °C`
const localDays = days => `Local day${days.length > 1 ? "s" : ""} ${days.join(", ")}`

// The ten retained rows as readable text beside the image (wraps at any width; never truncated).
export function Hot10Rows({ context }) {
  const multi = context.local_days.length > 1
  return h("div", { className: "hot10-preview-rows" },
    h("p", null, `${context.qualified_cities} of ${context.sampled_cities} sampled catalogue cities qualified. ${localDays(context.local_days)}${multi
      ? "; each row shows its own local day" : ""}. Forecasts, not observations, records or the world's hottest places.`),
    h("ol", { "aria-label": "Hot 10 ranked rows" }, context.rows.map(row => h("li", { key: row.rank, value: row.rank },
      h("strong", null, `${row.city}, ${row.country}`), " ",
      h("span", { className: row.departure_c > 0 ? "hot10-warm" : row.departure_c < 0 ? "hot10-cool" : undefined },
        `${signedC(row.departure_c)} vs normal`),
      h("span", { className: "hot10-row-detail" },
        ` · forecast ${row.forecast_high_c.toFixed(1)} °C, normal ${row.normal_high_c.toFixed(1)} °C · ${row.valid_date} (${row.timezone})`)))))
}

export function GraphicPreviewFigure({ value, url, originalURL = null }) {
  if (value.schema_version === 5) return h(PublishedFigure, { value, url, originalURL })
  const context = value.source_context
  const timing = context.kind === "hot10_bulletin" ? `${localDays(context.local_days)} · forecast daily highs`
    : context.kind === "crw_product_day"
    ? `Product day ${context.product_date} · L4 satellite analysis · ${context.valid_cells} of ${context.total_cells} sampled cells valid`
    : context.kind === "pm25_forecast_day"
    ? `${context.valid_date} · ${context.timezone} · model forecast`
    : context.kind === "ghcn_station_day"
      ? `Station ${context.station_id} · ${context.valid_date} source-calendar date · observed; reporting interval and timezone unknown`
    : `${context.acquired_at.slice(0, 16).replace("T", " ")} UTC (minute precision)`
  if (value.schema_version === 4) return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.delivery_text, width: value.width, height: value.height }),
    h(FullSizeImage, { url, alt: value.delivery_text, title: value.title }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", { className: "graphic-kind" }, context.kind === "hot10_bulletin" ? "Forecast departure table (sampled cities)"
        : context.kind === "crw_product_day" ? "Satellite-analysis anomaly chart (sampled cells, not a continuous surface)"
        : context.kind === "pm25_forecast_day" ? "Model forecast chart"
        : context.kind === "viirs_acquisition" ? "NOAA-20/NOAA-21 VIIRS satellite detections" : "MODIS satellite detections"),
      h("p", null, `${value.source} · ${timing}`),
      context.kind === "pm25_forecast_day" && h("p", null,
        `Forecast requested ${context.requested_at.slice(0, 16).replace("T", " ")} UTC; retrieved ${context.retrieved_at.slice(0, 16).replace("T", " ")} UTC. Retrieval is not a model run time, and a forecast never becomes an observation.`),
      h("p", null, value.scope),
      context.kind === "hot10_bulletin" && h(Hot10Rows, { context }),
      h(PostingWindow, { window: value.posting_window }),
      h("div", { className: "graphic-full-description" }, h("strong", null, "Image description sent to X"), h("p", null, value.delivery_text)),
      h("details", null, h("summary", null, "Expanded source details (not sent)"), h("p", { style: { whiteSpace: "pre-wrap" } }, value.expanded_description))))
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.alt_text, width: value.width, height: value.height }),
    value.schema_version === 3 && h(FullSizeImage, { url, alt: value.alt_text, title: value.title }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", null, `${value.source} · ${timing}`),
      context.kind === "ghcn_station_day" && h("p", null, `Archive retrieved ${context.retrieved_at}; comparison uses accepted source samples, not a certified record.`),
      h("p", null, value.scope),
      value.schema_version === 3
        ? h("div", { className: "graphic-full-description" }, h("strong", null, "Full graphic description"), h("p", null, value.alt_text))
        : h("details", null, h("summary", null, "Read the full graphic description"), h("p", null, value.alt_text))))
}

const FIRE_LABELS = { modis: "MODIS", viirs: "NOAA-20/NOAA-21 VIIRS" }

// Advisory join of the text's measured values with the graphic's own description.
export function TextGraphicAgreement({ text, value }) {
  if (!value || value.schema_version === 5) {
    return h("p", { className: "graphic-agreement", "data-status": "published" },
      "Software does not read a published image; compare its labels with the text yourself.")
  }
  const result = textGraphicAgreement(text, value.schema_version >= 4 ? value.delivery_text : value.alt_text)
  if (result.status !== "compared") return h("p", { className: "graphic-agreement", "data-status": result.status },
    "No measured values in the text to compare with the graphic description.")
  return h("p", { className: "graphic-agreement", "data-status": result.unmatched.length ? "unmatched" : "matched" },
    result.unmatched.length
      ? `Not stated in the graphic description: ${result.unmatched.join(", ")}. They may be correct from the source (a departure or multiple); check each before recording joint review.`
      : `Every measured value in the text (${result.compared}) also appears in the graphic description. This is not proof the image or text is correct.`)
}

// One set of attach/remove/joint-review controls for every Gist post-image family.
export function MediaControls({ draft, preview, reviewConfirmed, onConfirm, onAction, held = false, retainedInput = null,
  attestations = {}, onAttest = () => {} }) {
  const attached = draft.media_attachment_sha256
  const present = Object.hasOwn(draft, "media_attachment") || typeof attached === "string"
  const ready = preview.status === "ready" && [3, 4, 5].includes(preview.value?.schema_version)
  const delivery = ready && preview.value.schema_version >= 4
  const required = ready && preview.value.schema_version === 5 ? preview.value.inspection.required_attestations : []
  const attested = required.every(row => attestations[row.name] === true)
  const retained = retainedInput ? { retainedInputSha256: retainedInput } : {}
  const mediaSha = ready ? preview.value.media_descriptor_sha256 : null
  const matching = ready && typeof attached === "string" && /^[a-f0-9]{64}$/.test(attached) && attached === mediaSha
  const mutable = ["pending", "approved"].includes(draft.status) && !draft.publish_blocked
    && draft.review_status !== "conflict" && !draft.revision_conflicts?.length
  const canReview = matching && mutable && draft.status === "pending"
    && /^[a-f0-9]{64}$/.test(draft.editorial_policy?.policy_sha256 ?? "")
  const expectedRevision = draft.revision_identity
  return h("div", { className: "temperature-media-controls" },
    present ? h(React.Fragment, null,
      h("p", null, held ? "This draft has an attachment this dashboard cannot review or post. It stays held until you remove it."
        : matching ? (delivery ? "This image and its X image description are attached to the saved draft."
        : "This image and description are attached to the saved draft.")
        : "Build the current preview to inspect the attached image and description."),
      ready && !matching && !held && h("button", { type: "button", className: "btn sm", disabled: !mutable || !onAction,
        onClick: () => onAction?.("attach_graphic", { expectedRevision, expectedMediaSha256: mediaSha, ...retained }) }, "Replace attached graphic"),
      h("button", { type: "button", className: "btn sm", disabled: !mutable || !onAction,
        onClick: () => onAction?.("remove_graphic", { expectedRevision }) }, "Remove graphic"))
      : ready && h("button", { type: "button", className: "btn sm", disabled: !mutable || !onAction,
        onClick: () => onAction?.("attach_graphic", { expectedRevision, expectedMediaSha256: mediaSha, ...retained }) }, "Attach graphic"),
    canReview && h("div", { className: "workbench-panel", "aria-label": "Review text and attached graphic" },
      h("h3", null, "Review this text and graphic"),
      h("p", { className: "draft-text" }, draft.text),
      h(TextGraphicAgreement, { text: draft.text, value: preview.value }),
      h("p", null, delivery
        ? "Check this exact text, the image above, the image description sent to X and the expanded source details against the saved source evidence."
        : "Check this exact text, the image above and its full description against the saved source evidence."),
      h("label", null, h("input", { type: "checkbox", checked: reviewConfirmed, disabled: !onAction,
        onChange: event => onConfirm(event.target.checked) }), delivery
        ? " I checked the exact text, image, X image description and source details."
        : " I checked the exact text, image and full graphic description."),
      required.length > 0 && h("fieldset", { className: "graphic-attestations" },
        h("legend", null, "Published image checks (you, not software, confirm these)"),
        required.map(row => h("label", { key: row.name, style: { display: "flex", gap: 8, alignItems: "flex-start", minHeight: 44 } },
          h("input", { type: "checkbox", checked: attestations[row.name] === true, disabled: !onAction,
            onChange: event => onAttest(row.name, event.target.checked) }), h("span", null, row.text)))),
      h("button", { type: "button", className: "btn sm", disabled: !reviewConfirmed || !attested || !onAction,
        onClick: () => reviewConfirmed && attested && onAction?.("review", { reviewConfirmed: true, mediaReviewConfirmed: true,
          expectedMediaSha256: mediaSha, expectedPolicySha256: draft.editorial_policy.policy_sha256, expectedRevision,
          ...(required.length ? { publishedAttestations: Object.fromEntries(required.map(row => [row.name, true])) } : {}) }) },
        "Record joint review")))
}
export const TemperatureMediaControls = MediaControls

// The visible state line beside the controls (same inputs MediaControls derives).
export function GraphicState({ draft, preview, held = false }) {
  const attached = draft.media_attachment_sha256
  const present = Object.hasOwn(draft, "media_attachment") || typeof attached === "string"
  const ready = preview.status === "ready" && [3, 4, 5].includes(preview.value?.schema_version)
  const mediaSha = ready ? preview.value.media_descriptor_sha256 : null
  const matching = ready && typeof attached === "string" && /^[a-f0-9]{64}$/.test(attached) && attached === mediaSha
  const state = graphicState({ draft, preview, present, matching, held })
  // Plain text, not a second live region: the preview status above announces changes.
  return h("p", { className: "graphic-state", "data-graphic-state": state.key }, h("strong", null, state.label), ` ${state.detail}`)
}

// One explicit state for the selected draft's graphic; the text stays reviewable on its own.
// Source expiry comes from the preview's own posting disclosure; approval and the sender
// recheck it independently. A held or unavailable image never erases the text draft.
export function graphicState({ draft, preview, present, matching, held = false }) {
  const window = preview.status === "ready" ? preview.value?.posting_window : null
  const expired = window?.status === "unavailable"
  const reason = expired ? String(window.reason).replace(/\.$/, "") : ""
  if (held) return { key: "held", label: "Held:", detail: "this attachment cannot be reviewed or posted here; remove it to continue with text only." }
  if (present && preview.status === "error")
    return { key: "attached_unavailable", label: "Graphic unavailable:", detail: "see the reason above. The attached image cannot be approved; remove it to post the text alone." }
  if (present && matching && expired)
    return { key: "source_expired", label: "Source time passed:", detail: `${reason}. The attached image cannot be approved or sent; inspect it here or remove it to post the text alone.` }
  if (present && draft.review_status === "media_review_required")
    return { key: "needs_review", label: "Needs joint review:", detail: matching
      ? "the text, image or source changed since the last review. Review them together before approval."
      : "build the current preview, then review the text and graphic together before approval." }
  if (present) return { key: "attached", label: "Attached:", detail: draft.review_kind === "delegated_media"
    ? "reviewed together with this exact text (delegated, one manual post)." : "reviewed together with this exact text." }
  if (expired) return { key: "preview_expired", label: "Preview only, not postable now:", detail: `${reason}. It stays inspectable; the text can still be reviewed and posted without it.` }
  if (preview.status === "ready") return { key: "preview", label: "Preview only:", detail: "not attached; the text can still be reviewed and posted without it." }
  if (preview.status === "error") return { key: "unavailable", label: "Graphic unavailable:", detail: "the text draft is unchanged and can still be reviewed on its own." }
  return { key: "none", label: "No graphic attached:", detail: "build a preview to inspect one; the text can be reviewed on its own." }
}

const STORE_LABELS = {
  crw: ["Retained CRW source packet (SHA256)", "Build the sampled-cell anomaly chart from the retained CRW CSV packet. No new source fetch or AI generation."],
  radar: ["Retained published radar asset (SHA256)", "Inspect a retained NWS KTLX reflectivity frame for this warning. Nothing is fetched; the original stays unchanged."],
  cone: ["Retained published forecast cone (SHA256)", "Inspect a retained NHC forecast cone for this storm and advisory. Nothing is fetched; the original stays unchanged."],
}

// W10.3: why a typed retained input is refused before any request. Only the exact SHA256 identity
// printed by local retention is accepted; a URL, path or name is never fetched or looked up.
export const RETAINED_INPUT_REFUSAL_CODE = value => /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? "url"
  : /[\/\\]/.test(value) ? "path" : "identity"
export const RETAINED_INPUT_REFUSALS = {
  url: "A web address is never fetched for a post image. Retain the exact published file locally with its product and reuse references, then paste the SHA256 identity it prints.",
  path: "A file path is not read from here. Retain the file locally with scripts/retain_gist_media.py, then paste the SHA256 identity it prints.",
  identity: "This is not a retained identity. Paste the exact 64-character SHA256 printed by scripts/retain_gist_media.py.",
}

function SavedPreview({ request, family, fireSource, draft, onAction, storeFamily = null }) {
  const [preview, setPreview] = useState({ status: "idle" })
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const [attestations, setAttestations] = useState({})
  const attached = draft.media_attachment
  // Default: the attached input, else this draft's own collector-retained CRW packet (exact match only).
  const collected = storeFamily === "crw" ? retainedPacketReference(draft) : null
  const [retainedInput, setRetainedInput] = useState(attached?.source?.packet_artifact_sha256 ?? attached?.asset?.manifest_sha256
    ?? (collected && !collected.invalid ? collected.artifact_sha256 : ""))
  const inputId = useRef(`retained-input-${Math.random().toString(36).slice(2)}`)
  const controller = useRef(null)
  useEffect(() => {
    const instance = createGraphicPreviewController({ manifest, onChange: state => {
      setReviewConfirmed(false)
      setAttestations({})
      setPreview(state)
    } })
    controller.current = instance
    return () => { instance.dispose(); controller.current = null }
  }, [])
  const validInput = /^[a-f0-9]{64}$/.test(retainedInput)
  const startRequest = storeFamily ? (validInput ? mediaPNGRequest(draft, manifest, retainedInput) : null) : request
  const offered = storeFamily && preview.status === "ready" && retainedInput !== (preview.value.media_descriptor?.source?.packet_artifact_sha256
    ?? preview.value.media_descriptor?.asset?.manifest_sha256) ? { status: "idle" } : preview
  return h(React.Fragment, null,
    storeFamily && h("div", { className: "graphic-retained-input" },
      h("label", { htmlFor: inputId.current }, STORE_LABELS[storeFamily][0]),
      // A pasted URL, path or name stays visible so the refusal below can name it; nothing is fetched or looked up.
      h("input", { id: inputId.current, type: "text", inputMode: "text", spellCheck: false, autoComplete: "off", maxLength: 2048,
        value: retainedInput, "aria-invalid": retainedInput && !validInput ? "true" : undefined,
        "aria-describedby": `${inputId.current}-help${retainedInput && !validInput ? ` ${inputId.current}-invalid` : ""}`,
        style: { width: "100%", minHeight: 44, fontFamily: "monospace" },
        onChange: event => { setRetainedInput(event.target.value.trim().toLowerCase()); controller.current?.cancel() } }),
      h("p", { id: `${inputId.current}-help`, className: "text-muted" }, collected?.invalid
        ? "This draft's retained packet reference is malformed; the image is held."
        : collected ? "Selected from the packet the collector retained for this draft (same source leg, date, region and claim). "
          + "Any other packet is refused. Changing it discards the current preview."
        : "Printed by scripts/retain_gist_media.py after local retention. Changing it discards the current preview."),
      retainedInput && !validInput && h("p", { id: `${inputId.current}-invalid`, className: "draft-feedback error", "data-retained-input-refusal": RETAINED_INPUT_REFUSAL_CODE(retainedInput) },
        RETAINED_INPUT_REFUSALS[RETAINED_INPUT_REFUSAL_CODE(retainedInput)])),
    h("p", null, storeFamily ? STORE_LABELS[storeFamily][1] : draft.type === "air_quality_hazard"
      ? "Build a chart from the saved PM2.5 model forecast. No new source fetch or AI generation."
      : family === "hot10" ? "Build the ten-row table from the saved qualified Hot 10 bulletin. No new source fetch, re-ranking or AI generation."
      : family === "temperature" ? "Compare the saved observed station reading with its qualified archive samples. No new source fetch or AI generation."
      : `Preview the saved ${FIRE_LABELS[fireSource]} detections. Source and display checks can still withhold the graphic. No new source fetch or AI generation.`),
    h("button", { type: "button", className: "btn sm", disabled: preview.status === "loading" || !startRequest,
      onClick: () => controller.current?.start(startRequest) }, preview.status === "ready" ? "Rebuild preview" : "Preview graphic"),
    h("div", { role: "status", "aria-live": "polite" },
      preview.status === "loading" ? "Building the saved-source preview…" : preview.status === "error" ? preview.message : ""),
    preview.status === "ready" && (!storeFamily || preview.value.media_descriptor && retainedInput
      === (preview.value.media_descriptor.source?.packet_artifact_sha256 ?? preview.value.media_descriptor.asset?.manifest_sha256))
      && h(GraphicPreviewFigure, { value: preview.value, url: preview.url, originalURL: preview.originalURL }),
    family && h(MediaControls, { draft, onAction, reviewConfirmed, onConfirm: setReviewConfirmed,
      // A preview for a different retained input is never offered for attachment or review.
      preview: offered, retainedInput: storeFamily && validInput ? retainedInput : null, attestations,
      onAttest: (name, checked) => setAttestations(current => ({ ...current, [name]: checked })) }),
    family && h(GraphicState, { draft, preview: offered }))
}

// Families with a complete reviewed Gist post-image path. Python independently
// qualifies every retained row; this only chooses which request to offer.
function postImageFamily(draft) {
  const store = storeFamilyFor(draft)
  if (store) return store
  if (isTemperaturePreviewType(draft?.type)) return "temperature"
  if (draft?.type === "air_quality_hazard") return "pm25"
  if (draft?.type === "fire" && ["modis", "viirs"].includes(firePreviewSourceStatus(draft))) return firePreviewSourceStatus(draft)
  if (draft?.type === "hot10" && hot10PreviewSourceStatus(draft) === "bulletin") return "hot10"
  return null
}

// W10.6: what this draft's image family needs and which input is missing here (display only).
export function GraphicRequirement({ family, draft, mediaStore = null }) {
  const row = draftGraphicRequirement(family, draft, mediaStore, family === "crw" ? retainedPacketReference(draft) : null)
  if (!row) return null
  return h("details", { className: "graphic-requirement", "data-graphic-family": row.family, "data-graphic-lane": row.lane },
    h("summary", { style: { minHeight: 44 } }, `${row.label}: ${LANE_TEXT[row.lane]}${row.missing.length ? ` · missing: ${row.missing[0]}` : ""}`),
    h("p", null, "Needs:"), h("ul", null, row.needs.map(need => h("li", { key: need }, need))),
    row.missing.length ? h("p", null, `Missing here: ${row.missing.join("; ")}. The text story is unaffected; post it without an image or supply the input.`)
      : h("p", null, row.lane === "native" ? "Nothing else is needed; source and display checks can still withhold the image."
        : "The store setting is present; access is checked only when you preview. This is not hosted or native rendering proof."))
}

export function GraphicPreview({ draft, editing = false, updating = false, onAction, mediaStore = null }) {
  const family = postImageFamily(draft)
  const present = Object.hasOwn(draft ?? {}, "media_attachment")
  const storeFamily = storeFamilyFor(draft)
  if (!["fire", "air_quality_hazard"].includes(draft?.type) && !family) {
    // A present attachment on a draft without a reviewed image path stays removable.
    return present && !editing && !updating ? h("section", { className: "graphic-preview", "aria-label": "Saved-source graphic preview" },
      h("h3", null, "Saved-source preview"),
      h(MediaControls, { draft, preview: { status: "idle" }, reviewConfirmed: false, onConfirm() {}, onAction, held: true }),
      h(GraphicState, { draft, preview: { status: "idle" }, held: true })) : null
  }
  const forecast = draft.type === "air_quality_hazard"
  const missingWindow = forecast && !draft.review_context?.two_bot?.bundle?.raw_signal_dump?.forecast_window
  const fireSource = draft.type === "fire" ? firePreviewSourceStatus(draft) : null
  const temperatureSource = family === "temperature" ? temperaturePreviewSourceStatus(draft) : null
  const request = family === "temperature" ? temperaturePNGRequest(draft, manifest)
    : family ? mediaPNGRequest(draft, manifest) : graphicRequest(draft, manifest)
  const sourceMissing = family === "temperature" ? temperatureSource !== "ghcn" : missingWindow || fireSource === "missing" || fireSource === "unsupported"
  return h("section", { className: "graphic-preview", "aria-label": "Saved-source graphic preview" },
    h("h3", null, "Saved-source preview"),
    family && h(GraphicRequirement, { family, draft, mediaStore }),
    h("p", { className: "graphic-preview-note" }, family
      ? `${present || draft.media_attachment_sha256 ? "A graphic is attached; review its current preview below." : "Preview only; not attached or approved."} Build the saved-source image, attach it, then review the text and graphic together.`
      : "Preview only; not attached or approved."),
    updating ? h("p", null, "Updating this draft. Build a new preview after it finishes.")
      : editing ? h("p", null, "Save or cancel your text edit before building a preview.")
      : !request ? h("p", null, "Refresh the saved draft and resolve any conflicting versions before previewing.")
        : missingWindow ? h("p", null, "The hourly forecast was not saved with this draft. A graphic is unavailable.")
          : family === "temperature" && temperatureSource !== "ghcn" ? h("p", null, "Qualified observed GHCN station evidence was not retained with this draft. No comparison preview is available.")
          : fireSource === "missing" ? h("p", null, "Saved fire source receipts are missing or incomplete. No graphic preview is available for this draft.")
          : fireSource === "unsupported" ? h("p", null, "This fire preview supports MODIS or NOAA-20/NOAA-21 VIIRS receipts from one product only. The saved source set is unsupported; no preview is available.")
          : h(SavedPreview, { key: `${draft.type}:${draft.status}:${graphicRequestKey(request)}`, request, family, fireSource, draft, onAction, storeFamily }),
    present && !editing && !updating && (!request || sourceMissing || !family)
      && h(MediaControls, { draft, preview: { status: "idle" }, reviewConfirmed: false, onConfirm() {}, onAction, held: !family }),
    present && !editing && !updating && (!request || sourceMissing || !family)
      && h(GraphicState, { draft, preview: { status: "idle" }, held: !family }))
}
