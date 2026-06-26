"""Open-Meteo budget and rate-limit exceptions."""
from __future__ import annotations

from collections import deque


class OpenMeteoSaturated(Exception):
    pass


class OpenMeteoBudget:
    """Rolling per-IP weight accountant + pacing primitive. Weight is
    per-location. `reserve` is minute headroom held back (e.g. for the Hot 10
    leaderboard, a separate process). `clock`/`sleep` are injected so pacing is
    fake-clock tested with no real time.
    """

    def __init__(self, *, per_minute, per_hour, per_day, reserve, clock, sleep):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.reserve = reserve
        self._clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()

    def _spent_within(self, seconds: float) -> int:
        cutoff = self._clock() - seconds
        return sum(w for t, w in self._events if t > cutoff)

    def _prune(self) -> None:
        cutoff = self._clock() - 86_400
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()

    def remaining_minute(self) -> int:
        return max(0, self.per_minute - self.reserve - self._spent_within(60))

    def can_spend(self, weight: int) -> bool:
        return (
            self._spent_within(60) + weight <= self.per_minute - self.reserve
            and self._spent_within(3600) + weight <= self.per_hour
            and self._spent_within(86_400) + weight <= self.per_day
        )

    def spend(self, weight: int) -> None:
        self._prune()
        self._events.append((self._clock(), weight))

    def forecast_batch_size(self, remaining_cities: int) -> int:
        return max(0, min(remaining_cities, self.remaining_minute()))

    def next_available_delay(self, weight: int) -> float:
        # Hour/day ceilings cannot be paced through within a run.
        if self._spent_within(3600) + weight > self.per_hour:
            raise OpenMeteoSaturated("hourly ceiling reached")
        if self._spent_within(86_400) + weight > self.per_day:
            raise OpenMeteoSaturated("daily ceiling reached")
        usable = self.per_minute - self.reserve
        spent_60 = self._spent_within(60)
        if spent_60 + weight <= usable:
            return 0.0
        need = (spent_60 + weight) - usable
        now = self._clock()
        freed = 0.0
        for t, w in self._events:
            if t <= now - 60:
                continue
            freed += w
            if freed >= need:
                return max(0.0, (t + 60) - now)
        raise OpenMeteoSaturated("weight exceeds usable minute budget")

    def wait_until_can_spend(self, weight: int) -> None:
        for _ in range(100_000):
            if self.can_spend(weight):
                return
            delay = self.next_available_delay(weight)
            if delay <= 0:
                return
            self._sleep(delay)
        raise OpenMeteoSaturated("pacing did not converge")
