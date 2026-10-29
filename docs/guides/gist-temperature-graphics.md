# Temperature graphics in the Workbench

The Gist Workbench can make a colour PNG from a saved GHCN station observation
and its retained archive comparison. No source download or model call is needed
for the image. High and low observations use warm and cool colours on a shared
zero-based scale. The chart names the station, source-calendar date, comparison
scope and archive cutoff. An accepted-sample comparison is not an official record;
reporting interval and timezone remain unknown when the source does not provide them.

1. Open a supported temperature draft and choose **Preview graphic**.
2. Check the station, date, values, comparison and full graphic description.
3. Choose **Attach graphic**, then build the current preview again.
4. Review the exact text, attached image and full description together. Confirm
   the review and choose **Record joint review**.
5. Use the existing **Approve + Post** action only when ready to publish. The
   usual required checks still apply. Attaching or reviewing never posts anything.

Changing text, source references or the attachment invalidates earlier review
and approval. An invalid or obsolete attachment can still be removed without a
working preview. Removal is a revision change and also needs a new review.

The worker reconstructs the PNG from the retained source, checks its exact image
and description identities, and rejects observations outside the existing zero
through four source-calendar-day window. A changed rendering environment needs a
new preview and review. Broken images never silently become text-only posts.
An uncertain upload or send stays held for reconciliation; do not repeatedly
approve the same uncertain delivery.

## Connect a quote with saved source facts

While editing a draft, select an exact quote in **Operator-selected source
references**, choose the retained facts to connect, and save the draft. These
connections record an operator's selection; they do not run checks or establish
that a claim is supported. Current references apply only to the exact saved text
and source snapshot. Earlier references remain in the history. Source or text
changes require an explicit new selection.

This release does not enable automatic collection, draft generation or publishing.
Only full retained GHCN comparator evidence is supported by this PNG path. Other
media kinds keep their existing restrictions.
