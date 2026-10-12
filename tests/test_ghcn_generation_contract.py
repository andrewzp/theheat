"""Bounded full/view, baseline footprint and original selector regressions."""
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import hashlib
import textwrap

import pytest

from src.two_bot import ghcn_claim_view as claim
from src.orchestrator.sources import open_meteo as source
from src.storage.ghcn_runtime_inputs import Baseline
from tests.test_ghcn_source_result_producer import complete_member as complete_member
from tests.test_ghcn_runtime_inputs import source_bytes as source_bytes

PARENT_CASCADE_SHA = "f3332cb65cf5a63aea912441c5b059462c197e87de8228818cb44ef65a93cf90"


def old_selector():
    raw=(Path(__file__).parent/"fixtures/ghcn-parent-selector.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest()==PARENT_CASCADE_SHA
    code="def original(bot_state,bundle,records_cluster_suppressed_ids,city_elevations):\n"
    code+="    signal_counts=dict.fromkeys(('all_time','monthly','absolute_extreme','anomaly','calendar'),0)\n    simultaneous_record_stations=[]\n"
    code+=textwrap.indent(raw.decode(),"    ")
    code+="    return (strongest_signal,strongest_score,strongest_event_id,strongest_headline,strongest_facts,strongest_type,strongest_city,signal_counts,simultaneous_record_stations)\n"
    namespace=dict(vars(source))
    exec(compile(code,"exact42ea-parent-cascade","exec"),namespace)
    return namespace["original"]


@pytest.mark.parametrize("field",tuple(claim.TYPES)+("simultaneous","suppressed","duplicate"))
def test_shared_selector_matches_original_priority_fields_counts_and_side_effects(complete_member,field):
    _,full=complete_member
    member=deepcopy(full)
    if field in claim.TYPES:
        for name in claim.TYPES:
            if name!=field:
                setattr(member,name,None)
    state={"drafts":[],"publish_ledger":{}}
    if field=="duplicate":
        from tests.test_ghcn_time_integrity import draft
        state["drafts"]=[draft(event_day=member.signal_date,sid=member.station_id)]
    suppressed={member.calendar_date_high.event_id} if field=="suppressed" else set()
    first,second=deepcopy(state),deepcopy(state)
    with source._suppression_context(first,source="invented-selector",run_id="invented"):
        expected=old_selector()(first,deepcopy(member),suppressed,{})
    with source._suppression_context(second,source="invented-selector",run_id="invented"):
        actual=source._select_individual_signal(second,deepcopy(member),suppressed,{})
    assert tuple(getattr(actual,f.name) for f in fields(actual))==expected
    assert first==second
    if field=="simultaneous":
        assert actual.signal==member.all_time_high and actual.legacy_type=="all_time_high"
        assert actual.counts["all_time"]==1 and sum(actual.counts.values())==1


@pytest.mark.parametrize("change",["replace","empty_wal","empty_shm","empty_journal","symlink","missing","io"])
def test_fixed_baseline_metadata_fence_distinguishes_changes(tmp_path,monkeypatch,change):
    db,manifest=tmp_path/"baseline.sqlite",tmp_path/"manifest"
    db.write_bytes(b"invented-not-opened-sqlite")
    manifest.write_bytes(b"invented")
    baseline=Baseline(db,manifest,"a"*64,"b"*64)
    before=claim.baseline_footprint(baseline)
    if change=="replace":
        replacement=tmp_path/"new"
        replacement.write_bytes(db.read_bytes())
        replacement.replace(db)
    elif change.startswith("empty_"):
        Path(str(db)+"-"+change[6:]).write_bytes(b"")
    elif change=="symlink":
        other=tmp_path/"other"
        db.rename(other)
        db.symlink_to(other)
    elif change=="missing":
        manifest.unlink()
    else:
        original=Path.lstat
        def denied(path):
            if path==Path(str(db)+"-shm"):
                raise PermissionError("invented uncertainty")
            return original(path)
        monkeypatch.setattr(Path,"lstat",denied)
    if change in {"symlink","missing","io"}:
        with pytest.raises((ValueError,OSError)):
            claim.baseline_footprint(baseline)
    else:
        assert claim.baseline_footprint(baseline)!=before
