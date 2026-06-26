from __future__ import annotations

from dataclasses import dataclass, field

MIN_MEAN_SAMPLES = 30  # below this, a monthly mean is too sparse to fire an anomaly


@dataclass
class CityThresholds:
    city: str
    as_of: str
    years_of_data: int
    all_time_max: tuple[float, int] | None = None
    all_time_min: tuple[float, int] | None = None
    monthly_max: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_min: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_mean: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    wetbulb_max: tuple[float, int] | None = None

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "as_of": self.as_of,
            "years_of_data": self.years_of_data,
            "all_time_max": list(self.all_time_max) if self.all_time_max else None,
            "all_time_min": list(self.all_time_min) if self.all_time_min else None,
            "monthly_max": {k: list(v) for k, v in self.monthly_max.items()},
            "monthly_min": {k: list(v) for k, v in self.monthly_min.items()},
            "monthly_mean": {k: list(v) for k, v in self.monthly_mean.items()},
            "wetbulb_max": list(self.wetbulb_max) if self.wetbulb_max else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityThresholds":
        def pair(v):
            return tuple(v) if v else None

        return cls(
            city=d["city"],
            as_of=d["as_of"],
            years_of_data=int(d.get("years_of_data", 0)),
            all_time_max=pair(d.get("all_time_max")),
            all_time_min=pair(d.get("all_time_min")),
            monthly_max={k: tuple(v) for k, v in (d.get("monthly_max") or {}).items()},
            monthly_min={k: tuple(v) for k, v in (d.get("monthly_min") or {}).items()},
            monthly_mean={k: tuple(v) for k, v in (d.get("monthly_mean") or {}).items()},
            wetbulb_max=pair(d.get("wetbulb_max")),
        )
