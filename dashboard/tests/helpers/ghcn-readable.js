// Invented display-shape fixture only. Its placeholder digests certify nothing.
export function readableDraft() {
  const scope = { sample_count: 2, expected_count: 2, coverage_fraction: 1, complete: true,
    years_with_samples: 1, start: "2020-01-01", cutoff: "2020-01-02", conflicting_dates: [],
    previous_value_c: 28, previous_date: "2020-01-02", requested_comparison_cutoff: "2026-09-07",
    source_calendar_count: 2, source_coverage_complete: false, source_coverage_fraction: 0.1,
    source_gap_count: 2, source_latest_cell: "2020-01-02", source_missing_count: 0,
    source_qc_rejected_count: 0, verified_source_cutoff: null, monthly_years: { "01": 1 },
    monthly_samples: { "01": 2 }, record_dates: { all_time: "2020-01-02", monthly: { "01": "2020-01-02" } },
    record_values_c: { all_time: 28, monthly: { "01": 28 } } }
  const names = ["temperature_2m_max", "temperature_2m_min"]
  const baseline = { schema_version: "theheat-ghcn-complete-readable-table-v1", source_product: "noaa-ghcn-daily-v2",
    station_id: "USC99000001", evidence_type: "observed", comparison_scope: "available_source_accepted_station_samples",
    comparison_before: "2026-09-08", cutoff: "2026-09-07", requested_comparison_cutoff: "2026-09-07",
    retrieved_at: "2026-09-09T12:00:00Z", source_payload_sha256: "1".repeat(64), reconciled: true,
    revision_id: "2".repeat(64), variables: Object.fromEntries(names.map(name => [name, structuredClone(scope)])),
    wire_profile: { format: "ghcn-complete-readable-table-v1", original_schema_version: 2, all_null_group: "absent_calendar_key_not_zero" },
    calendar_table: { variables: names, columns: ["calendar_day", ...names.flatMap(name =>
      ["accepted_years", "accepted_samples", "previous_date", "previous_c"].map(field => `${name}:${field}`))],
      rows: [["01-01", 1, 1, "2020-01-01", 28, null, null, null, null],
        ["01-02", 1, 1, "2020-01-02", 28, 1, 1, "2020-01-02", -5]] } }
  return { id: "invented-readable-display", type: "all_time_high", status: "pending", review_context: { two_bot: { bundle: {
    signal_kind: "open_meteo_archive_high", where: "Invented display", when: "2026-09-08",
    historical_context: { baseline: { same_document_baseline: "raw_signal_dump.evidence.baseline", full_baseline_sha256: "3".repeat(64) } },
    raw_signal_dump: { evidence: { source_product: "noaa-ghcn-daily-v2", evidence_type: "observed",
      station_id: "USC99000001", valid_date: "2026-09-08", retrieved_at: "2026-09-09T12:00:00Z", baseline } },
  } } } }
}
