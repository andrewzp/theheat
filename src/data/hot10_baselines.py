"""Which normals product the Hot10 ranks against: one explicit product per run, never a fallback.

``THEHEAT_HOT10_NORMALS_PRODUCT`` unset, empty or ``meteostat-normals-point-v1``
keeps today's behaviour exactly (``open_meteo.load_normals`` over
``data/normals.csv``). Exactly ``noaa-ghcnd-monthly-mean-tmax-v1`` reads only
that product's own installed file. Any other value refuses the run's Hot10
rather than guessing. A missing or refused file for the selected product leaves
every place without a normal (the bulletin holds); it never reads the other file.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from src.data import ghcnd_monthly_normals as ghcnd

FLAG = "THEHEAT_HOT10_NORMALS_PRODUCT"
LEGACY = "meteostat-normals-point-v1"
GHCND = ghcnd.PRODUCT
PRODUCTS = (LEGACY, GHCND)


class UnknownNormalsProduct(ValueError):
    """The flag names no known product; the Hot10 run is refused, not defaulted."""


def selected_product(environ: Mapping[str, str] | None = None) -> str:
    value = (os.environ if environ is None else environ).get(FLAG, "")
    if value in ("", LEGACY):
        return LEGACY
    if value == GHCND:
        return GHCND
    raise UnknownNormalsProduct("hot10_normals_product_unknown")


def inventory_value(environ: Mapping[str, str] | None = None) -> str:
    """Runtime-inventory projection: the selected product, or ``invalid`` (never echoes the raw value)."""
    try:
        return selected_product(environ)
    except UnknownNormalsProduct:
        return "invalid"


def load_alternative(product: str, report: dict[str, Any] | None = None) -> dict[str, dict]:
    """The non-legacy product's own installed file only (the legacy path stays ``open_meteo.load_normals``)."""
    if product != GHCND:
        raise UnknownNormalsProduct("hot10_normals_product_unknown")
    return ghcnd.load_normals(ghcnd.DEFAULT_INSTALLED, report)


__all__ = ["FLAG", "GHCND", "LEGACY", "PRODUCTS", "UnknownNormalsProduct", "inventory_value", "load_alternative",
           "selected_product"]
