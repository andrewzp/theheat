"""Source runner for GRACE ice mass."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_ice_mass(bot_state: BotState, current_run: dict | None) -> None:
    # 12. GRACE-FO ice mass (Greenland + Antarctica).
    # Monthly-cadence source with 1-2 month lag. Run once per week on
    # Mondays. Per-region short-circuit via ice_mass_last_seen prevents
    # re-processing the same published month. Annual cap: 8 tweets/year.
    if date.today().weekday() == 0:
        print("[alerts] Checking GRACE ice mass...")
        for region in ("greenland", "antarctica"):
            region_key = f"ice_mass_{region}"
            im_start = time.perf_counter()
            try:
                if _ice_annual_cap_reached(bot_state):
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="skipped", note="annual cap reached",
                    )
                    continue
                readings = _fetch_strict(ice_mass.fetch_grace_mass, region=region)
                if not readings:
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="success", observed=0,
                    )
                    continue
                latest_month = readings[-1].month
                last_seen = bot_state.get("ice_mass_last_seen", {}).get(region)
                if last_seen == latest_month:
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="skipped",
                        note=f"already processed {latest_month}",
                    )
                    continue

                ice_record = ice_mass.detect_monthly_record(readings, cast(dict, bot_state))
                if ice_record is None:
                    ice_record = ice_mass.detect_cumulative_milestone(readings, cast(dict, bot_state))

                source_promoted = 0
                if ice_record and not state.is_duplicate(bot_state, ice_record.event_id):
                    score = score_ice_mass_event(
                        region=ice_record.region,
                        kind=ice_record.kind,
                        monthly_delta_gt=ice_record.monthly_delta_gt,
                        previous_worst_gt=ice_record.previous_worst_gt,
                        threshold_gt=ice_record.threshold_gt,
                    )
                    if _should_draft(score, ice_record.event_id):
                        source_promoted = 1
                        earliest = readings[0].month
                        earliest_year = int(earliest.split("-")[0])
                        years_of_record = date.today().year - earliest_year
                        # Narrow the kind-conditional optional fields once;
                        # see IceMassRecord (src/data/ice_mass.py): monthly_*
                        # set for "monthly_loss_record", threshold_*+current_*
                        # set for cumulative milestones.
                        if ice_record.kind == "monthly_loss_record":
                            assert ice_record.monthly_delta_gt is not None
                            assert ice_record.month is not None
                            headline = f"{ice_record.region.title()}: largest monthly ice loss on record"
                        else:
                            assert ice_record.threshold_gt is not None
                            assert ice_record.current_mass_gt is not None
                            headline = f"{ice_record.region.title()}: cumulative loss crosses {abs(int(ice_record.threshold_gt))} Gt"
                        facts = [
                            _fact("Region", ice_record.region.title()),
                            _fact("Latest month", ice_record.month or latest_month),
                        ]
                        if ice_record.kind == "monthly_loss_record":
                            assert ice_record.monthly_delta_gt is not None
                            facts.append(_fact(
                                "Monthly loss",
                                f"{abs(ice_record.monthly_delta_gt):.0f} Gt",
                            ))
                            if ice_record.previous_worst_gt is not None:
                                facts.append(_fact(
                                    "Previous worst",
                                    f"{abs(ice_record.previous_worst_gt):.0f} Gt "
                                    f"({ice_record.previous_worst_month})",
                                ))
                        else:
                            assert ice_record.threshold_gt is not None
                            assert ice_record.current_mass_gt is not None
                            facts.append(_fact(
                                "Cumulative threshold",
                                f"{abs(int(ice_record.threshold_gt))} Gt",
                            ))
                            facts.append(_fact(
                                "Current anomaly",
                                f"{abs(ice_record.current_mass_gt):.0f} Gt below 2002 baseline",
                            ))
                        review_context = _review_context(
                            source="NASA GRACE-FO / JPL PODAAC",
                            source_key=region_key,
                            headline=headline,
                            current_run=current_run,
                            facts=facts,
                        )
                        from src.two_bot.intern import build_ice_mass_bundle
                        ice_bundle = build_ice_mass_bundle(
                            ice_record,
                            years_of_record=years_of_record,
                            archive_start_year=earliest_year,
                        )
                        _ice_record = ice_record

                        def _on_success(
                            _bs: BotState = bot_state,
                            _record = _ice_record,
                        ) -> None:
                            _increment_ice_annual_count(_bs)
                            # Update the extreme trackers on success.
                            if _record.kind == "monthly_loss_record":
                                assert _record.monthly_delta_gt is not None
                                assert _record.month is not None
                                _bs.setdefault("ice_mass_max_loss", {})[_record.region] = {
                                    "gt": _record.monthly_delta_gt,
                                    "month": _record.month,
                                }
                            else:
                                assert _record.threshold_gt is not None
                                _bs.setdefault("ice_mass_last_milestone", {})[_record.region] = _record.threshold_gt

                        _enqueue_story_candidate(
                            bot_state,
                            bundle=ice_bundle,
                            score=score,
                            source=region_key,
                            legacy_type="ice_mass_record",
                            event_id=ice_record.event_id,
                            review_context=review_context,
                            on_draft_success=_on_success,
                        )

                # Always mark the month as seen so we don't reprocess until data updates.
                bot_state.setdefault("ice_mass_last_seen", {})[region] = latest_month
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="success", observed=len(readings),
                    promoted=source_promoted, drafted=0,
                )
            except SourceSkipped as e:
                print(f"[alerts] ice_mass {region} skipped: {e}")
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="skipped", note=str(e),
                )
            except Exception as e:
                print(f"[alerts] ice_mass {region} error: {e}")
                state.log_error(bot_state, region_key, str(e))
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="failed", error=str(e),
                )
    else:
        for region in ("greenland", "antarctica"):
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, bot_state, f"ice_mass_{region}", skipped_start,
                status="skipped", note="Runs Mondays only",
            )
    return
