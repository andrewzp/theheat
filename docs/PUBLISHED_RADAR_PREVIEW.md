# Published radar in the local editor

This experimental workflow attaches an unchanged published NWS radar image to an eligible local severe-weather draft. It preserves the image's full colors, labels, legend, timestamp and attribution. The original GIF remains available beside a pixel-equivalent PNG preview. It does not generate weather imagery with an AI model.

The implementation is deliberately bounded to the NWS KTLX local standard product and Oklahoma City. It is not a global radar collector, a general chart importer or an automated visual fact checker. Production remains on Gist; collection, drafting and automatic publishing remain paused. Local review and delivery-fixture receipts do not authorize a public post.

## Source and time qualification

A retained NWS response must contain an actual meteorological Tornado Warning with the exact catastrophic-damage and observed-detection tags, using Alert or Update message type. The original event name and tags remain attributed to NWS. The observed tag can represent radar detection; it does not establish an eyewitness account or surface damage.

The same retained response supplies the warning identifier, time fields and polygon. The named Oklahoma City point must lie strictly inside that qualified polygon. Human review must also confirm that point's context in the raster. Neither condition establishes that the image covers the whole warning footprint. Missing times, unsupported polygons, other radar stations or unqualified source relationships hold the graphic.

The full displayed radar minute must fit inside the warning's effective interval. The editorial ceiling is 15 minutes from the frame time, further shortened by every applicable source, check and authority deadline. New work cannot renew that window. A saved historical image remains readable after expiry, editing or rejection; reading it does not restore approval.

## Retaining an already acquired image

`scripts/retain_published_radar.py` reads operator-owned local files and retains their exact bytes and metadata in the existing local PostgreSQL media storage. It performs no download, provider call, review or publication. The original product URL is fixed; there is no arbitrary image-fetch or upload proxy.

The command requires explicit local socket/database/user configuration and absolute input, original, acquisition-receipt, product-reference and reuse-reference paths. Each file must be an ordinary owned mode0600 file, without symlink paths, within its existing bound. The metadata hashes and sizes must match the original and reference bytes. This records unreviewed metadata; a hash proves identity, not the truth of a raster label.

The existing ingress and media worker accept `--published-radar-inputs`, an owned configuration with exactly `schema_version: 1` and `selections`. Its bounded mapping associates at most16 retained source-brief hashes with retained radar-input hashes. It is reread for current authority. There is no browser field for selecting arbitrary storage objects, source URLs or eligibility metadata.

## Preview, review and recovery

The worker accepts only a static600×550GIF of at most2MiB. It keeps the original and converts it to PNG without cropping, recoloring, overlays or resizing; decoded RGBA pixels must agree. The PNG remains under8MiB and the existing total artifact bound still applies. The published family contains exactly input.json, original.gif, preview.png and alt.txt. Generated graphics retain their separate existing five-asset format.

The editor shows the retained preview, source/time/context and a protected link to inspect the original at full size. The normal five text-and-graphic confirmations remain required, together with three published-product confirmations: raster labels match the metadata, the named-point context is correct, and unchanged-product reuse conditions are met. None is preselected. A review note is required. The fixed published-radar description identifies reflectivity and its limited context; it makes no unsupported subtype or impact claim.

Attaching the jointly reviewed image changes the draft revision. Four fresh checks must then bind that exact text and graphic before a publisher can park approval locally. Changing text or media, withdrawing review or losing current eligibility invalidates the relevant authority. Original assets and receipts remain retained for history and fresh-database restore. The separate invented local delivery rehearsal never contacts X or Bluesky.

## Acceptance limits

Automated tests use invented warning responses, model responses, images and operator actions. Their receipt establishes only the workflow exercised. They do not establish real-source authenticity, a human visual judgment, browser usability, live delivery or better engagement. Actual browser and production acceptance are recorded separately from local PostgreSQL, HTTP, native image and restore tests. Other published charts, radar products and global coverage remain work in the wider graphics plan.
