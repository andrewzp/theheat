# Live content: automatic text, opt-in forecasts and native graphics

How the automatic text supply and native graphics work after the live-content
program, what holds each one, and what an operator does next. Nothing here grants
new authority: the global publication epoch/pause, the daily cap, current model
checks, final safety and every unknown-delivery fence still apply first.

## Automatic text (all kinds)

- **One writer sample, no revise.** Copy usually runs 90–170 characters (Unicode
  scalars). There is no minimum, and required forecast, sampled-universe, window
  and source qualifiers stay in.
- **Hard 200-scalar automatic cap** (`src/editorial/automatic_text.py`,
  `dashboard/lib/automatic-text.js`). A longer draft is saved complete for manual
  review with `automatic_text_hold`. It is never truncated. The cap is checked at
  both arming paths, at the dashboard `auto_approve` route and again before send.
- **Text only.** Automatic copy that refers to a chart, map, image or table is
  held (`automatic_text_implies_media`). Automatic sends never attach an image,
  including the legacy Hot10 card.
- **Recheck.** An edit, a candidate selection, restored text or a source change
  drops the old checks. Eligibility returns only when checks are bound to the
  current text and source.
- **Critic quality details** (`quality`, `quality_note`) are soft craft notes for
  reviewers. They are never a verdict, a human rating or feedback. Andrew's
  optional post feedback stays in the existing post-feedback route.

## Hot10

- **What is ranked.** Only sampled catalogue cities with a qualified Open-Meteo
  forecast and a `meteostat-normals-point-v1` normal for the same point and month
  are ranked (`src/editorial/hot10_contract.py`).
- **Ten or nothing.** Fewer than ten qualified places → `hot10_short_slate`, and
  nothing is drafted.
- **Final boundary.** The send holds when the retained bulletin changed, its
  leader's local day ended or its capture is over 12 hours old.
- **Rollout dependency.** The checked-in `data/normals.csv` is legacy, so
  production Hot10 holds until root runs `scripts/build_normals.py` (a live
  Meteostat retrieval) and lands its output.

## PM2.5 and dust forecasts (default off)

- **Separate flags, exact `1` only.** `THEHEAT_PM25_FORECAST_AUTO_TEXT` and
  `THEHEAT_DUST_FORECAST_AUTO_TEXT`. With both off, nothing new is fetched and
  these drafts stay manual-only.
- **One bounded re-read.** With a flag on, one GET re-reads the same city and
  local day (one attempt, 10 s, 64 KiB) at three points: paid generation (a hold
  keeps the slot), admission (a changed source is never saved) and automatic
  send before safety (not again after the durable intent).
- **Automatic eligibility.** Also requires text only, forecast wording, a window
  that has not ended, a retained source no more than 6 hours old, and either the
  first post or a tier rise for that city and day. Any unknown earlier delivery
  in the same city/day blocks it.
- **Dust.** A dust peak is never compared with a 24-hour mean, a WHO period or a
  multiple. Only a supplied PM10 clause carries the PM10 anchor.

## Native graphics and delegated review

- **Hot10 graphic (Gist family `gist_hot10_bulletin_v1`).** Built only from the
  retained qualified bulletin: all ten ranked rows, each city's point normal and
  local day, the sampled universe and the source identity. The image is a
  1200×1500 departure table (bands from one shared zero, warm above normal, cool
  below; every value also written as text). A missing, duplicate or changed row,
  a changed ranking, a non-°C unit, a normal for another month or a label that
  does not fit refuses the image; the text draft stays usable. The editor preview
  lists the ten rows as text, and attach/replace/remove and joint review use the
  same actions as the other image families. Approval and sending recheck every
  ranked row's local day and capture age. Automatic sends stay text only.
- **Delivered graphics.** The Workbench lists delivered posts with a native
  image. Inspecting one rebuilds the exact delivered PNG from its retained recipe
  (checked byte-for-byte against what was sent) with the posted text and image
  description, even after the current draft changed. If the renderer changed
  since delivery, the bytes are not rebuilt and the text and receipt stay shown.
- **Legacy Hot10 card.** `render_hot10_bulletin` (default-off
  `THEHEAT_HOT10_CARD_ENABLED`) stays manual-only and never attaches beside a
  selected image.
- **Delegated joint review** (`delegated_media`). Native kinds only. The trusted
  operator seam is `src/editorial/delegated_media_review.record_verified`, which
  verifies the retained authorization (`theheat.delegated-review-authorization/v1`)
  and receipt (`theheat.delegated-native-media-review/v1`) against the current
  text, image, description, source and policy. It covers one manual post: never
  automatic, never `human_media`, never a scientist verdict. Published products
  with attestations stay human-held.

## Health

- **Sources view.** Shows each source's plain outcome and next action (for
  example: access expired, baseline unavailable, too few qualified inputs,
  selector/budget hold, checked copy rejected, no event). It also shows checked
  sampled denominators. Unknown stays unknown, and nothing claims global recall.
- **Named blocks.** GPM's expired Earthdata token is a named access block; a
  stored key is not recovery.
- **Threshold baseline.** Release `thresholds-latest` has no
  `station_thresholds.sqlite` asset (957,243,392 bytes pinned), so the GHCN leg
  holds until root rebuilds and uploads it.
- **Draft counts.** Posted and rejected drafts are retained history, not a
  backlog.

## Next rollout steps (root)

1. Regenerate the generated artifacts (source registry → editorial policy →
   graphic runtime), review the change and run Linux CI. Include
   `tests/test_live_content_native_journeys.py`.
2. Land qualified Hot10 normals and the station-thresholds asset (both live
   retrievals).
3. Decide on the PM2.5 flag, then the dust flag, each under the standing
   automatic authority. Watch the Sources view outcome rows after each run.
