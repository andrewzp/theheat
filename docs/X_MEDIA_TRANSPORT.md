# X image transport

The production `twitter._get_upload_api()` factory uses the current v2 JSON image
and metadata endpoints through `XMediaAPI`. Tweepy 4.17 supplies the existing
OAuth1 user-token signing; its `Client` exposes no current media methods. No
credential grant or provider entitlement is established by constructing a client.

An upload carries base64 PNG bytes and `media_category: tweet_image` to
`https://api.x.com/2/media/upload`. A successful response must provide a canonical
`data.id`. Metadata sends that exact ID with `metadata.alt_text.text` to
`https://api.x.com/2/media/metadata`, and its acknowledgement must name the same
ID. The existing tweet-creation helper remains unchanged. No image-size reduction,
alt truncation, async processing poll, alternate endpoint, retry or text fallback
is performed. Each request owns and closes its session, disables environment
proxies and redirects, and uses five-second connection/read timeouts. Successful
response bodies are limited to 64 KiB; invalid or incomplete success evidence does
not authorize the next phase.

Source/render/review checks remain upstream. The transport's PNG signature and
5 MiB byte checks are not image decoding or source verification. Alt text is limited
to 1,000 Unicode scalars and valid UTF-8. The wrappers preserve the existing
`x_publish` ticket and upload → alt → create outbox stages. A complete upload or
metadata rejection remains distinct from a lost or unusable response; unknown
delivery never grants a resend. Existing stored unknown deliveries are untouched.

`delivery_transport`, `delivery_receipts` and the
`credentialless-loopback-v1` platform-description profile deliberately remain the
frozen legacy experimental wire. They test that historical protocol's durable
bindings and recovery only. They do **not** qualify the current production media
endpoint. `test_x_media_current_contract.py` exercises the actual production
factory and real request/OAuth preparation through a no-network intercept with
invented credentials. Neither fixture establishes account entitlement, production
joint review, cross-host byte readback or an image receipt on X. Automatic images
remain off until the separate rollout criteria are met.

The current contract is documented by [X's upload reference](https://docs.x.com/x-api/media/upload-media)
and [official OpenAPI](https://docs.x.com/openapi.json), including both OAuth2 and
OAuth1 UserToken security alternatives. The upload reference's OAuth2 example is
not evidence that existing OAuth1 credentials require replacement.
