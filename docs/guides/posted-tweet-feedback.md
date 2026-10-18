# Give feedback on a published tweet

In the dashboard, open **Make the next tweet better**, below the draft queue.
Choose a published tweet and read its exact sentence, then rate punch, clarity
and economy from 1 (weak) to 5 (strong). Economy asks whether every word earns
its place. Add a short note if useful, confirm the ratings are your own, and save.
Nothing is pre-scored. Saving feedback never edits, approves or publishes a tweet.

Only confirmed X posts with an exact matching delivery receipt are available.
Older posts without that evidence stay out of this form. Missing engagement
metrics remain unknown; an editorial rating is not a fact check, an independent
blind comparison, or evidence that model-written tweets have improved.

If a save cannot be confirmed, use **Check saved feedback**. This only reads the
request's receipt; it does not send another rating. The pending request survives
reload in this browser tab. If the request is still unconfirmed, keep its ID for
investigation rather than sending a replacement. The form remains held until the
save is resolved. Closing the browser tab can discard its pending receipt.

The form uses a dedicated secret feedback Gist, with one auxiliary file per explicit save,
without rewriting bot state. New saves stop once 100 feedback files are visible. Concurrent saves can
cross that admission threshold; their receipts remain readable. Full archive
reads are bounded at 1,000 files, with exact request-ID recovery still available
beyond that bound. Gist is not a transaction service; concurrent edits and provider outages
remain limitations. Experimental SQLite/local-command previews do not write this
production feedback archive. The separately configured feedback archive must be
secret; the API refuses a public archive. Existing production bot-state visibility
is left unchanged. Ratings do not automatically tune prompts or change
publishing settings; review actual outcomes before proposing an experiment.
