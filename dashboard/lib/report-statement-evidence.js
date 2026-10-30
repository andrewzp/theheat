// Editor view of attributed report statements carried into a draft's brief
// (src/editorial/report_supply.py -> bundle.human_impact, evidence_class
// "attributed_report_statement"). Browser-safe inspection of the retained bundle
// only: it does not authenticate the publisher, re-read the article, re-run the
// quote check or grant approval. Every statement keeps its exact quote, the
// attribution, the source date, the original language and translation decision,
// and the source revision (retained-text digest that binds the quote, plus the
// supplied report reference). A partial or altered row is unreadable, never
// partially shown as if it were evidence.
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const text = (value, max) => typeof value === "string" && value.trim().length > 0 && value.length <= max
const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const STATES = new Set(["source_language", "translation_human_reviewed"])
const RETRIEVAL = new Set(["full_text_retained", "excerpt_only"])

function statement(item) {
  if (!object(item) || item.evidence_class !== "attributed_report_statement") throw new Error("class")
  if (!text(item.value, 500) || !text(item.claim, 2000) || !text(item.claim_id, 100) || !text(item.attribution, 200)
      || !text(item.source_name, 200) || !text(item.as_of, 40) || !RETRIEVAL.has(item.retrieval_status)) throw new Error("fields")
  const url = new URL(item.url)
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("url")
  const translation = item.translation
  if (!object(translation) || !STATES.has(translation.state) || translation.original_text !== item.value
      || translation.independent_confirmation !== false || (Array.isArray(translation.unresolved) && translation.unresolved.length)) {
    throw new Error("translation")
  }
  if (translation.state === "translation_human_reviewed"
      && (!text(translation.translated_text, 2000) || !text(translation.translation_identity, 200) || item.claim !== translation.translated_text)) {
    throw new Error("translation")
  }
  if (translation.state === "source_language" && item.claim !== item.value) throw new Error("translation")
  if (!hash(item.report_sha256) || !hash(item.retained_text_sha256) || !hash(item.target_bundle_sha256)) throw new Error("revision")
  const joined = item.physical_join_id !== undefined || item.physical_episode_id !== undefined
  if (joined && (!text(item.physical_join_id, 200) || !text(item.physical_episode_id, 300))) throw new Error("join")
  return {
    claim_id: item.claim_id, quote: item.value, claim: item.claim, attribution: item.attribution,
    source_name: item.source_name, url: url.href, source_date: item.as_of, retrieval: item.retrieval_status,
    language: translation.original_language ?? null, translation_state: translation.state,
    translated_text: translation.state === "translation_human_reviewed" ? translation.translated_text : null,
    translation_identity: translation.translation_identity ?? null,
    retained_text_sha256: item.retained_text_sha256, report_sha256: item.report_sha256,
    episode: joined ? { join_id: item.physical_join_id, episode_id: item.physical_episode_id,
      window: object(item.claim_window) || typeof item.claim_window === "string" ? item.claim_window : null } : null,
  }
}

export function reportStatementsForDisplay(draft) {
  const twoBot = draft?.review_context?.two_bot
  const bundled = Array.isArray(twoBot?.bundle?.human_impact) ? twoBot.bundle.human_impact : []
  const rows = bundled.filter(item => object(item) && item.evidence_class === "attributed_report_statement")
  if (!rows.length) return { status: "unsupported" }
  try {
    const statements = rows.map(statement)
    // The reviewer-facing copy must be the very rows the checks saw in the retained bundle.
    const saved = Array.isArray(twoBot?.human_impact)
      ? twoBot.human_impact.filter(item => object(item) && item.evidence_class === "attributed_report_statement") : []
    if (JSON.stringify(saved) !== JSON.stringify(rows)) throw new Error("copy")
    const cited = typeof twoBot.cited_impact === "boolean" ? twoBot.cited_impact : null
    return { status: "present", statements, cited }
  } catch { return { status: "unreadable" } }
}
