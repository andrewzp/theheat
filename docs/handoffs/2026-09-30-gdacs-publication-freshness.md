# GDACS RSS publication freshness

The RSS fallback previously treated the newest event start as feed freshness.
Future event windows could therefore make stale data appear current, while an
ongoing event with an old start could appear stale despite a recent update.

The parser now checks one aware UTC clock. Feed freshness uses channel `pubDate`,
or the latest usable item update only when channel publication is absent.
Each selected alert independently uses nonempty `gdacs:datemodified`, otherwise
item `pubDate`. An invalid preferred field does not fall back to another clock.
Naive, missing and malformed publication times cannot establish freshness; more
than five minutes in the future is invalid. The existing inclusive three UTC
calendar-day limit is preserved, rather than changed to an elapsed 72-hour limit.

Unverifiable selected alerts stop before drafting. Diagnostics distinguish no
qualifying alerts from withheld alerts, record counts by reason, and preserve
independently valid peers. Explicit invalid channel publication fails the source;
source-wide structural validation and bounded fallback attempts remain in force.

Provenance preserves event windows separately from source update times. Fresh
publication does not establish observed intensity, landfall or confirmed impacts.
Unknown cyclone countries remain unknown. Required editorial checks still apply,
and the generated policy manifest binds the revised source rule.

Validation uses synthetic fixed-clock cases for stale/future dates, timezone
boundaries, missing and invalid updates, mixed valid/withheld events, diagnostics
and zero drafting for withheld alerts. Historical fixture publication clocks are
explicitly labeled synthetic. A privately retained RSS response supports an
offline before/after timing comparison, not a model-quality or weather-truth claim.

This change covers RSS fallback only. Primary JSON freshness, structural
per-item containment, production source recovery and measured editorial benefit
remain separate work. It changes no runtime models, writer sample count, billing
flags or publishing activation.
