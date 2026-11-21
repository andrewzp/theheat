"""Collector-only discovery from an already downloaded IMERG frame.

HDF5/NumPy stay outside the retained/preview contract. Geography is a fixed inland
cartographic mask; a selected cell never establishes an area maximum or impact.
"""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import math
import re

from src.data import rainfall_grid as contract

MAX_FILE_BYTES = 128 * 1024 * 1024
SHAPE = (1, 3600, 1800)


def _attribute(value):
    """Value-level decoding only; the caller must verify stored HDF5 types.

    Do not stringify objects or join multi-valued attributes. NumPy's fixed
    string scalar extraction removes its storage padding; embedded NUL remains
    invalid. Unit/calendar interpretation belongs to the exact callers below.
    """
    import numpy as np

    if type(value) is np.ndarray:
        if value.shape not in {(), (1,)}:
            return None
        if value.dtype.kind == "S":
            if value.dtype.itemsize > 128:
                return None
        elif value.dtype.kind == "O":
            import h5py

            if h5py.check_string_dtype(value.dtype) is None:
                return None
        else:
            return None
        value = value.item()
    if type(value) in (np.bytes_, np.str_):
        value = value.item()
    if type(value) is bytes:
        if len(value) > 128:
            return None
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if type(value) is str and 0 < len(value) <= 128 and all(" " <= char <= "~" for char in value):
        return value
    return None


def _text_attribute(dataset, name):
    """Validate stored type/shape/width/padding before h5py can discard them."""
    import h5py
    import numpy as np

    if name not in dataset.attrs:
        return None
    with closing(dataset.attrs.get_id(name)) as attribute, closing(attribute.get_type()) as storage:
        shape = attribute.shape
        if shape not in {(), (1,)} or storage.get_class() != h5py.h5t.STRING:
            return None
        if storage.get_cset() not in {h5py.h5t.CSET_ASCII, h5py.h5t.CSET_UTF8}:
            return None
        if storage.is_variable_str():
            return _attribute(dataset.attrs[name])
        width = storage.get_size()
        if not 0 < width <= 128:
            return None
        padding = storage.get_strpad()
        if padding not in {h5py.h5t.STR_NULLTERM, h5py.h5t.STR_NULLPAD, h5py.h5t.STR_SPACEPAD}:
            return None
        buffer = np.zeros(shape, dtype=f"S{width}")
        # Identical file/memory types preserve all original fixed-width bytes,
        # including a nonzero suffix that high-level NULLTERM conversion hides.
        attribute.read(buffer, mtype=storage)
        raw = buffer.tobytes()
        if padding == h5py.h5t.STR_SPACEPAD:
            raw = raw.rstrip(b" ")
        else:
            terminator = raw.find(b"\x00")
            if terminator >= 0:
                if any(raw[terminator:]):
                    return None
                raw = raw[:terminator]
            elif padding == h5py.h5t.STR_NULLTERM:
                return None
        return _attribute(raw)


def _dataset(handle, path, shape, *, integer=False):
    import h5py

    # No external/soft links, virtual data or external raw storage. All source
    # values must be in the downloaded file, not another local/network resource.
    parts = path.strip("/").split("/")
    for length in range(1, len(parts) + 1):
        link = handle.get("/".join(parts[:length]), getlink=True)
        contract.require(isinstance(link, h5py.HardLink), "rainfall_grid_dataset_invalid")
    dataset = handle.get(path)
    contract.require(isinstance(dataset, h5py.Dataset), "rainfall_grid_dataset_invalid")
    contract.require(dataset.shape == shape and dataset.dtype.kind in ("iu" if integer else "fiu")
                     and dataset.dtype.itemsize <= 8 and not dataset.is_virtual and not dataset.external,
                     "rainfall_grid_dataset_invalid")
    for name, identity in (("scale_factor", 1), ("add_offset", 0)):
        if name in dataset.attrs:
            value = _numeric_attribute(dataset.attrs[name])
            contract.require(value == identity, "rainfall_grid_packed_data_unsupported")
    return dataset


def _numeric_attribute(value):
    import numpy as np

    number = np.asarray(value)
    # NetCDF represents scalar numeric attributes as one-element HDF5 arrays.
    # Accept only that exact scalar representation, never an ambiguous array.
    contract.require(number.shape in {(), (1,)} and number.dtype.kind in "fiu" and number.dtype.itemsize <= 8,
                     "rainfall_grid_attribute_invalid")
    scalar = float(number.reshape(()))
    # NaN is a valid missing-value sentinel, but never a scaling identity.
    return scalar


def _sentinels(dataset):
    return tuple(_numeric_attribute(dataset.attrs[name]) for name in ("_FillValue", "missing_value")
                 if name in dataset.attrs)


def _missing(dataset, values, *, sentinels=None):
    import numpy as np

    result = np.zeros(np.shape(values), dtype=bool)
    for missing in _sentinels(dataset) if sentinels is None else sentinels:
        result |= np.isnan(values) if math.isnan(missing) else values == missing
    return result


def _source_time(dataset, day):
    units = _text_attribute(dataset, "units")
    calendar = _text_attribute(dataset, "calendar")
    contract.require(calendar in {"gregorian", "standard", "proleptic_gregorian"}
                     and isinstance(units, str), "rainfall_grid_time_invalid")
    match = re.fullmatch(r"(seconds|hours|days) since (\d{4}-\d{2}-\d{2})"
                         r"(?:[ T](\d{2}:\d{2}:\d{2}))?(?: UTC|Z| ?\+00:00)?", units)
    contract.require(match is not None, "rainfall_grid_time_invalid")
    assert match is not None
    try:
        origin = datetime.fromisoformat(match[2] + "T" + (match[3] or "00:00:00")).replace(tzinfo=UTC)
        contract.require(origin.date() >= date(1582, 10, 15), "rainfall_grid_time_invalid")
        scalar = float(dataset[0])
        contract.require(math.isfinite(scalar) and not bool(_missing(dataset, scalar)), "rainfall_grid_time_invalid")
        source = origin + timedelta(seconds=scalar * {"seconds": 1, "hours": 3600, "days": 86400}[match[1]])
    except (ValueError, OverflowError) as exc:
        raise contract.GridHeld("rainfall_grid_time_invalid") from exc
    contract.require(source.date() == day and source.microsecond == 0, "rainfall_grid_time_invalid")
    return source.isoformat().replace("+00:00", "Z")


def scan(handle, dataset, grid, raw, *, day: date, product: str, now=None):
    """Finite local pass, with one qualified maximum per supported inland tile.

    Dataset shape/dtype must be checked before the caller materializes `grid`.
    Return data is owned by this call, never a retained global buffer or verdict.
    """
    import numpy as np

    contract.require(product == "late" and len(raw) <= MAX_FILE_BYTES,
                     "rainfall_grid_product_invalid")
    contract.require(grid.shape == SHAPE, "rainfall_grid_dataset_invalid")
    path = dataset.name.strip("/")
    contract.require(path in {"precipitation", "Grid/precipitation"}, "rainfall_grid_dataset_invalid")
    # Reject dual-layout ambiguity instead of mixing coordinates from one copy
    # with values from another. The legacy city parser retains its old behavior.
    other = "Grid/precipitation" if path == "precipitation" else "precipitation"
    contract.require(handle.get(other, getlink=True) is None, "rainfall_grid_dataset_ambiguous")
    _dataset(handle, path, SHAPE)
    parent = path.rpartition("/")[0]

    def node(name, shape, **options):
        return _dataset(handle, f"{parent}/{name}" if parent else name, shape, **options)

    units = _text_attribute(dataset, "units")
    contract.require(units in contract.UNITS, "rainfall_grid_units_invalid")
    lon_node, lat_node = node("lon", (3600,)), node("lat", (1800,))
    contract.require(_text_attribute(lon_node, "units") == "degrees_east"
                     and _text_attribute(lat_node, "units") == "degrees_north",
                     "rainfall_grid_axes_invalid")
    longitude, latitude = lon_node[...], lat_node[...]
    contract.require(np.all(np.isfinite(longitude)) and np.all(np.isfinite(latitude))
                     and not np.any(_missing(lon_node, longitude)) and not np.any(_missing(lat_node, latitude))
                     and np.all(np.abs(longitude - (-179.95 + np.arange(3600) * .1)) < .0001)
                     and np.all(np.abs(latitude - (-89.95 + np.arange(1800) * .1)) < .0001),
                     "rainfall_grid_axes_invalid")
    source_time = _source_time(node("time", (1,)), day)
    age = contract.clock(now) - datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
    contract.require(timedelta(0) <= age <= contract.MAX_AGE, "rainfall_completed_window_expired")
    counts = node("precipitation_cnt", SHAPE, integer=True)
    value_missing, count_missing = _sentinels(dataset), _sentinels(counts)
    table, _names = contract.geography()
    digest = sha256(raw).hexdigest()
    rows = []
    diagnostics = dict(tiles_examined=0, cells_examined=0, incomplete_cells=0,
                       invalid_value_cells=0, outside_range_cells=0, qualifying_cells=0,
                       qualifying_tiles=0)
    for (x, y) in sorted(table):
        values = grid[0, x * 10:x * 10 + 10, y * 10:y * 10 + 10]
        valid_counts = counts[0, x * 10:x * 10 + 10, y * 10:y * 10 + 10]
        complete = (valid_counts == 48) & ~_missing(counts, valid_counts, sentinels=count_missing)
        finite = np.isfinite(values) & (values >= 0) & ~_missing(dataset, values, sentinels=value_missing)
        in_range = (values >= 150) & (values <= 1000)
        eligible = complete & finite & in_range
        diagnostics["tiles_examined"] += 1
        diagnostics["cells_examined"] += 100
        diagnostics["incomplete_cells"] += int(np.count_nonzero(~complete))
        diagnostics["invalid_value_cells"] += int(np.count_nonzero(complete & ~finite))
        diagnostics["outside_range_cells"] += int(np.count_nonzero(complete & finite & ~in_range))
        diagnostics["qualifying_cells"] += int(np.count_nonzero(eligible))
        if not np.any(eligible):
            continue
        diagnostics["qualifying_tiles"] += 1
        # Flattening is column then row, so equal values choose the lowest
        # global column/row regardless of table, watchlist or input XML order.
        index = int(np.argmax(np.where(eligible, values, -np.inf)))
        dx, dy = divmod(index, 10)
        rows.append(dict(schema=contract.SCHEMA, source_url=contract.SOURCE_URL,
                         source_product=product, product_version="V07C", source_date=day.isoformat(),
                         source_time_utc=source_time, source_units=units,
                         column=x * 10 + dx, row=y * 10 + dy, mm_per_day=float(values[dx, dy]),
                         valid_half_hours=int(valid_counts[dx, dy]), source_file_sha256=digest,
                         geography_sha256=contract.TABLE_SHA256))
    return {"schema": "theheat.imerg-grid-discovery/v1", "status": "qualified", "rows": rows,
            "diagnostics": {**diagnostics, "cartographic_regions": len(set(table.values())),
                            "geography_sha256": contract.TABLE_SHA256,
                            "scope": "Supported inland tiles only; unexamined cells unknown, not zero. "
                                     "One successful-frame revisit; no weather coverage or uptime guarantee."}}
