// Advisory mirror of src/two_bot/copy_gates.py for the editor (bundle-blind rules).
// The Python module is the generation gate; this file only shows the same notes
// beside the current text. Notes never approve, rewrite or grade a draft, and an
// empty list is not an editorial, factual or safety pass. Paired vectors live in
// tests/fixtures/copy_gate_vectors.json and must stay identical on both sides.

export const COPY_GATES_VERSION = "copy-gates-v1"
const MAX_EXCERPT = 80

export const COPY_MESSAGES = Object.freeze({
  source_led_opener: "Lead with the place and the fact, not the source, model or product; attribution and forecast labels follow the fact.",
  generic_explanatory_ending: "End on the fact or a sourced consequence; a generic reminder/highlighting/climate ending adds words without news.",
  too_many_sentences: "One complete sentence is the default; a second only for essential qualification or a sourced consequence.",
  invented_danger: "Danger or health wording needs the same wording in an attributed source warning; none is supplied.",
  second_sentence: "A second sentence must be essential qualification or a sourced consequence.",
  over_automatic_length: "Over 200 characters: cannot post automatically; shorter usually reads better.",
  danger_wording_needs_source: "Danger or health wording needs an attributed source warning saying so.",
})

const URL = /https?:\/\/\S+/gi
const SOURCE_PHRASE_OPENER = /^(?:according\s+to|per|via|citing|data\s+from|figures\s+from|readings\s+from|new\s+data\s+from|satellite\s+data\s+from)\b/i
const ARTICLE_SOURCE_OPENER = new RegExp(
  "^(?:an?|the|new|latest|today's|this\\s+week's)\\s+"
  + "(?:[A-Za-z0-9][A-Za-z0-9_.'/-]*\\s+){0,4}?"
  + "(?:models?|forecasts?|analysis|reanalysis|dataset|data|product|bulletin|advisory|"
  + "outlook|estimates?|readings?|observations?|measurements?)\\s+"
  + "(?:now\\s+)?(?:puts?|shows?|showed|has|have|places?|projects?|indicates?|suggests?|says|"
  + "finds|found|estimates?|forecasts?|predicts?|reports?|reported|flags?|flagged|records?|"
  + "recorded|registers?|registered|detects?|detected|calls\\s+for|warns?|warned)\\b", "i")
const NAMED_SOURCE_OPENER = new RegExp(
  "^(?:CAMS|Copernicus|ERA5|ECMWF|GFS|GHCN(?:d|-Daily)?|FIRMS|MODIS|VIIRS|IMERG|GPM|NASA|"
  + "NOAA|NWS|NHC|JTWC|JMA|GDACS|USGS|NSIDC|FEMA|WMO|Open-Meteo|Meteostat|Coral\\s+Reef\\s+Watch|"
  + "CRW|HMS|AEMET|IMD|SAWS|Met\\s+Office|BoM|DWD|KMA|CMA|PAGASA)(?:'s)?(?=[\\s:,.]|$)")
const SEP = "(?:[,;:]|\\s-{1,2}|\\s—|—|\\s–)\\s*"
const ENDING_REMINDER = new RegExp(SEP
  + "(?:an?|another|the\\s+latest)\\s+(?:[A-Za-z-]+\\s+){0,2}?(?:reminder|sign|signal|testament|illustration|example|symbol|"
  + "snapshot|glimpse|wake-up\\s+call)\\s+(?:of|that|to)\\b[^.!?]*[.!?]?\\s*$", "i")
const ENDING_REMINDER_SENTENCE = new RegExp(
  "(?:^|[.!?]\\s+)(?:it's|it\\s+is|this\\s+is|that's|that\\s+is|another|a)\\s+"
  + "(?:[A-Za-z-]+\\s+){0,2}?(?:reminder|sign|signal|testament|illustration|example|symbol|"
  + "wake-up\\s+call)\\s+(?:of|that|to)\\b[^.!?]*[.!?]?\\s*$", "i")
const ENDING_PARTICIPLE = new RegExp(SEP
  + "(?:highlighting|underscoring|underlining|illustrating|demonstrating|showcasing|emphasi[sz]ing|"
  + "signall?ing\\s+(?:a|the|how|that)|raising\\s+concerns?)\\b[^.!?]*[.!?]?\\s*$", "i")
const ENDING_CLIMATE = /\bas\s+(?:the\s+|our\s+)?(?:climate|planet|world|earth|globe)\s+(?:warms|heats(?:\s+up)?|changes|keeps\s+warming|continues\s+to\s+warm)\b[^.!?]*[.!?]?\s*$/i
const CLIMATE_SLOGAN = /\b(?:climate\s+change|global\s+warming)\s+(?:in\s+action|is\s+here|is\s+real|at\s+work)\b/i
const WINK_KICKER = /(?:^|[.!?]\s+)(?:the\s+calendar\s+says\s+[A-Za-z]+|and\s+it's\s+only\s+[A-Za-z]+|a\s+record\s+is\s+a\s+record|let\s+that\s+sink\s+in|read\s+that\s+again|you\s+read\s+that\s+right)[.!?]?\s*$/i
const DANGER = /\b(?:life[-\s]threatening|dangerous(?:ly)?|deadly|lethal|hazardous|unhealthy|unsafe|toxic|potentially\s+fatal|fatal|health\s+(?:risk|threat|hazard|emergency)|threat\s+to\s+life|threatens?\s+lives|brace\s+for)\b/i
const BOUNDARY = /[.!?]["')\]]*\s+(?=[A-Z0-9"'(])/g
const ABBREVIATIONS = new Set([
  "st", "mt", "ft", "no", "vs", "approx", "est", "dr", "jr", "sr", "inc", "co", "corp", "gov",
  "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
  "a.m", "p.m", "u.s", "u.k", "u.n", "e.g", "i.e", "etc",
])
const BLOCKING = new Set(["source_led_opener", "generic_explanatory_ending", "too_many_sentences", "invented_danger"])

export function visibleCopy(text) {
  if (typeof text !== "string") return ""
  return text.replace(URL, " ").replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .split(/\s+/).filter(Boolean).join(" ")
}

export function sentences(text) {
  const body = visibleCopy(text)
  const result = []
  let start = 0
  for (const match of body.matchAll(BOUNDARY)) {
    const stop = match.index + 1
    const words = body.slice(start, stop - 1).split(/\s+/).filter(Boolean)
    const token = words.length ? words[words.length - 1].replace(/^["'(]+/, "").toLowerCase() : ""
    if (ABBREVIATIONS.has(token) || (token.length === 1 && /[a-z]/i.test(token))) continue
    result.push(body.slice(start, stop).trim())
    start = match.index + match[0].length
  }
  const tail = body.slice(start).trim()
  if (tail) result.push(tail)
  return result
}

function excerpt(value) {
  const chars = Array.from(value.split(/\s+/).filter(Boolean).join(" "))
  return chars.length <= MAX_EXCERPT ? chars.join("") : chars.slice(0, MAX_EXCERPT - 1).join("") + "…"
}

function note(code, text) {
  return Object.freeze({ code, blocking: BLOCKING.has(code), excerpt: excerpt(text), message: COPY_MESSAGES[code] })
}

// Bundle-blind: danger wording is advisory here because the editor cannot see the
// attributed source warning; the Python generation gate checks the bundle.
export function copyNotes(text) {
  if (typeof text !== "string") return []
  const body = visibleCopy(text)
  if (!body) return []
  const notes = []
  for (const pattern of [SOURCE_PHRASE_OPENER, NAMED_SOURCE_OPENER, ARTICLE_SOURCE_OPENER]) {
    const match = body.match(pattern)
    if (match) { notes.push(note("source_led_opener", match[0])); break }
  }
  for (const pattern of [ENDING_REMINDER, ENDING_REMINDER_SENTENCE, ENDING_PARTICIPLE, ENDING_CLIMATE, CLIMATE_SLOGAN, WINK_KICKER]) {
    const match = body.match(pattern)
    if (match) { notes.push(note("generic_explanatory_ending", match[0].replace(/^[\s,;:.!?\-—–]+/, ""))); break }
  }
  const parts = sentences(body)
  if (parts.length >= 3) notes.push(note("too_many_sentences", parts[2]))
  else if (parts.length === 2) notes.push(note("second_sentence", parts[1]))
  const danger = body.match(DANGER)
  if (danger) notes.push(note("danger_wording_needs_source", danger[0]))
  const scalars = Array.from(text).length
  if (scalars > 200) notes.push(note("over_automatic_length", `${scalars} characters`))
  return notes
}
