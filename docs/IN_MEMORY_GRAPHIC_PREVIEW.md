# In-memory scientific graphic rendering

Install `requirements-graphics.txt` for local rendering and the full offline test
suite. Normal bot imports still do not load ReportLab or invoke graphics. The
existing local CLI also requires its explicitly supplied PDF rasterizer.

`src.media.evidence_graphic_render.render_svg(template, evidence,
expected_evidence_sha256=...)` uses the same qualified drawing as local preview
packages. It returns UTF-8 SVG bytes, a SHA-256 digest, complete alt text, title,
scope, dimensions and an exact renderer/evidence binding. It writes no assets and
calls no model, source, PDF generator or subprocess. It works from a Python source
zip without extracting the font or code. No HTTP endpoint or dashboard integration
is activated by this library.

All existing source qualification runs before the optional renderer. Scientific
values, types, dates and qualifications are unchanged. Unsupported source stories,
edited projections, unreadable labels and SVG output exceeding 1,000,000 bytes are
refused. Fonts are embedded; the in-memory SVG omits the external SVG DTD. The
existing local five-asset package preserves its serialization and rasterizer
binding. Changes to renderer code create new identities; old packages are not
rewritten or reauthorized.

The returned identity includes the evidence hash, template/version, renderer and
adapter/contract/font hashes and ReportLab version. It is not a signature, source
authentication, scientific freshness check, semantic text/graphic review or posting
approval. A hosted caller must separately authenticate requests, select and bind
the current saved draft, enforce time/input/concurrency limits, prevent private
asset caching or leakage, and discard stale results. This helper's byte ceiling is
not a process memory or CPU limit. Hosting compute and storage costs are unmeasured.
