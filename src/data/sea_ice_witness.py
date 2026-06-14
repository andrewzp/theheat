"""OSI SAF sea-ice concentration witness for NSIDC sea-ice extent.

The primary NSIDC CSV is still the archive of record for this source. This
witness only serves when the primary is unavailable/stale, using the public
OSI SAF 401-b concentration grids hosted by MET Norway THREDDS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from xml.etree import ElementTree

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data._witness import tag_source_leg
from src.data.sea_ice import SeaIceReading
from src.data.source_status import SourceFetchError

OSI_SAF_LEG = "osi_saf"
THREDDS_CATALOG_ROOT = "https://thredds.met.no/thredds/catalog/osisaf/met.no/ice/conc"
THREDDS_FILESERVER_ROOT = "https://thredds.met.no/thredds/fileServer/"
_FILE_RE = re.compile(r"ice_conc_(nh|sh)_polstere-100_multi_(\d{8})1200\.nc$")


@dataclass(frozen=True)
class OsiSafFile:
    url: str
    data_date: str
    name: str


def latest_file_url_from_catalog(catalog_xml: str, *, hemisphere: str) -> OsiSafFile:
    """Select the newest OSI SAF NetCDF file for ``hemisphere`` from a catalog."""
    code = _hemisphere_code(hemisphere)
    try:
        root = ElementTree.fromstring(catalog_xml)
    except ElementTree.ParseError as exc:
        raise SourceFetchError(f"OSI SAF catalog parse failed: {exc}") from exc

    candidates: list[OsiSafFile] = []
    for node in root.findall(".//{*}dataset"):
        name = str(node.get("name") or "")
        url_path = str(node.get("urlPath") or "")
        match = _FILE_RE.match(name)
        if match is None or match.group(1) != code or not url_path:
            continue
        yyyymmdd = match.group(2)
        data_date = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        candidates.append(
            OsiSafFile(
                url=_fileserver_url(url_path),
                data_date=data_date,
                name=name,
            )
        )

    if not candidates:
        raise SourceFetchError(f"OSI SAF catalog had no {hemisphere} concentration files")
    return max(candidates, key=lambda item: item.data_date)


def reading_from_netcdf_bytes(
    content: bytes,
    *,
    hemisphere: str,
    data_date: str,
) -> SeaIceReading:
    """Convert an OSI SAF concentration grid into a SeaIceReading extent."""
    try:
        from netCDF4 import Dataset
        import numpy as np
    except ImportError as exc:
        raise SourceFetchError("OSI SAF sea ice witness requires netCDF4") from exc

    try:
        with Dataset("osi_saf_sea_ice.nc", memory=content) as dataset:
            ice_conc = dataset.variables["ice_conc"]
            grid = np.ma.array(ice_conc[0, :, :] if ice_conc.ndim == 3 else ice_conc[:, :])
            fill_value = getattr(ice_conc, "_FillValue", None)
            if fill_value is not None:
                grid = np.ma.masked_equal(grid, fill_value)
            grid = np.ma.masked_invalid(grid)
            sea_ice_cells = np.ma.masked_less(grid, 15.0)

            xc = np.ma.array(dataset.variables["xc"][:], dtype=float)
            yc = np.ma.array(dataset.variables["yc"][:], dtype=float)
            cell_area_km2 = _axis_spacing_km(xc, np) * _axis_spacing_km(yc, np)
            extent_million_km2 = round((int(np.ma.count(sea_ice_cells)) * cell_area_km2) / 1_000_000, 3)
    except KeyError as exc:
        raise SourceFetchError(f"OSI SAF NetCDF schema drift: missing {exc}") from exc
    except (OSError, RuntimeError) as exc:
        raise SourceFetchError(f"OSI SAF NetCDF read failed: {exc}") from exc

    event_id = f"sea_ice_{hemisphere.lower()}_{data_date}"
    return SeaIceReading(
        hemisphere=hemisphere,
        extent_million_km2=extent_million_km2,
        date=data_date,
        event_id=event_id,
    )


def fetch_osi_saf_sea_ice(
    hemisphere: str = "Arctic",
    *,
    strict: bool = False,
) -> list[SeaIceReading]:
    """Fetch the latest OSI SAF concentration grid for one hemisphere."""
    try:
        selected = _latest_osi_saf_file(hemisphere)
        response = fetch_with_retry(selected.url, timeout=45, attempts=2, backoff_base=1.0)
        reading = reading_from_netcdf_bytes(
            response.content,
            hemisphere=hemisphere,
            data_date=selected.data_date,
        )
        assert_freshness(reading.date, "sea_ice", max_age_days=5)
        return tag_source_leg([reading], OSI_SAF_LEG)
    except (requests.RequestException, SourceFetchError, ValueError, TypeError) as exc:
        if strict:
            raise SourceFetchError(f"OSI SAF sea ice fetch failed for {hemisphere}: {exc}") from exc
        return []


def _latest_osi_saf_file(hemisphere: str) -> OsiSafFile:
    errors: list[str] = []
    candidates: list[OsiSafFile] = []
    for catalog_url in _catalog_urls():
        try:
            response = fetch_with_retry(catalog_url, timeout=30, attempts=2, backoff_base=1.0)
            candidates.append(latest_file_url_from_catalog(response.text, hemisphere=hemisphere))
        except (requests.RequestException, SourceFetchError) as exc:
            errors.append(f"{catalog_url}: {exc}")
            continue
    if candidates:
        return max(candidates, key=lambda item: item.data_date)
    detail = "; ".join(errors) if errors else "no catalogs checked"
    raise SourceFetchError(f"OSI SAF catalog lookup failed for {hemisphere}: {detail}")


def _catalog_urls(*, today: date | None = None) -> list[str]:
    today = today or date.today()
    current_month = today.replace(day=1)
    previous_month = (current_month - timedelta(days=1)).replace(day=1)
    months = [current_month, previous_month]
    return [f"{THREDDS_CATALOG_ROOT}/{month.year}/{month.month:02d}/catalog.xml" for month in months]


def _fileserver_url(url_path: str) -> str:
    if url_path.startswith("http://") or url_path.startswith("https://"):
        return url_path
    return THREDDS_FILESERVER_ROOT + url_path.lstrip("/")


def _hemisphere_code(hemisphere: str) -> str:
    if hemisphere == "Arctic":
        return "nh"
    if hemisphere == "Antarctic":
        return "sh"
    raise SourceFetchError(f"Unsupported sea-ice hemisphere: {hemisphere}")


def _axis_spacing_km(values, np) -> float:
    axis = np.ma.compressed(values)
    if len(axis) < 2:
        raise SourceFetchError("OSI SAF NetCDF schema drift: grid axis too short")
    diffs = np.abs(np.diff(axis))
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        raise SourceFetchError("OSI SAF NetCDF schema drift: zero grid spacing")
    return float(np.median(diffs))
