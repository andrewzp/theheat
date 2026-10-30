// Paired with src/editorial/automatic_text.py: the hard automatic TEXT cap.
// Unicode scalar values, so a non-BMP character counts once in both runtimes; a
// lone surrogate is malformed. This only withholds automatic scheduling or
// sending. It never truncates or rewrites; manual review keeps its 280 limit.

export const AUTOMATIC_TEXT_MAX_SCALARS = 200
export const OVER_CAP = "automatic_text_over_200_scalars"
export const MALFORMED = "automatic_text_malformed_unicode"
export const IMPLIES_MEDIA = "automatic_text_implies_media"
export const HOLD_MESSAGES = Object.freeze({
  [OVER_CAP]: "Automatic text is limited to 200 characters; this complete draft stays available for manual review.",
  [MALFORMED]: "Draft text has malformed Unicode and cannot be published automatically.",
  [IMPLIES_MEDIA]: "Automatic posts are text only; this copy refers to an image, chart, map or table that is not sent.",
})
// Automatic posts never carry an image, so copy may not point at one (paired with automatic_text.py).
const MEDIA_REFERENCE = /\b(?:charts?|maps?|graphics?|images?|pictured|photos?|infographics?|tables?|attached|see (?:below|above))\b/i

export function scalarCount(text) {
  if (typeof text !== "string") throw new Error("Draft text must be a string")
  if (!text.isWellFormed()) throw new Error("Malformed Unicode text")
  return Array.from(text).length
}

export function automaticTextHold(text) {
  let count
  try {
    count = scalarCount(text)
  } catch {
    return MALFORMED
  }
  if (count > AUTOMATIC_TEXT_MAX_SCALARS) return OVER_CAP
  return MEDIA_REFERENCE.test(text) ? IMPLIES_MEDIA : null
}
