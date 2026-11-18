"""Weather and hourly comfort data from Open-Meteo. Free, no key."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL_SECONDS = 20 * 60
USER_AGENT = "refillmap/0.1 (github.com/fuleinist/refillmap)"

HOURLY_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "uv_index",
    "precipitation_probability",
    "wind_speed_10m",
)


@dataclass
class HourlyComfort:
    time: str
    temp_c: float | None
    apparent_c: float | None
    humidity: float | None
    uv_index: float | None
    rain_chance: float | None
    wind_kmh: float | None


@dataclass
class Weather:
    available: bool
    source: str
    fetched_at: str
    timezone: str
    hourly: list[HourlyComfort]
    reason: str = ""

    def now(self, when: datetime) -> HourlyComfort | None:
        if not self.hourly:
            return None
        target = when.replace(minute=0, second=0, microsecond=0)
        best = None
        best_delta = None
        for hour in self.hourly:
            try:
                stamp = datetime.fromisoformat(hour.time)
            except ValueError:
                continue
            delta = abs((stamp - target).total_seconds())
            if best_delta is None or delta < best_delta:
                best, best_delta = hour, delta
        return best


class WeatherCache:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS weather (key TEXT PRIMARY KEY, created_at REAL, payload TEXT)")
        self.conn.commit()

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT created_at, payload FROM weather WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        created_at, payload = row
        if time.time() - created_at > CACHE_TTL_SECONDS:
            return None
        return json.loads(payload)

    def put(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO weather (key, created_at, payload) VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(payload, separators=(",", ":"))),
        )
        self.conn.commit()


def _fetch(lat: float, lon: float, timeout: float) -> dict:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(HOURLY_FIELDS),
        "forecast_days": "3",
        "timezone": "auto",
    }
    request = Request(
        f"{OPEN_METEO_URL}?{urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_weather(
    lat: float,
    lon: float,
    cache: WeatherCache | None = None,
    timeout: float = 20.0,
) -> Weather:
    key = f"{lat:.4f},{lon:.4f}"
    payload = cache.get(key) if cache else None
    if payload is None:
        try:
            payload = _fetch(lat, lon, timeout)
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            return Weather(
                available=False,
                source="Open-Meteo",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                timezone="UTC",
                hourly=[],
                reason=f"Open-Meteo fetch failed: {exc}",
            )
        if cache:
            cache.put(key, payload)

    hourly_block = payload.get("hourly") or {}
    times = hourly_block.get("time") or []
    rows: list[HourlyComfort] = []

    def value(name: str, index: int) -> float | None:
        series = hourly_block.get(name)
        if not series or index >= len(series):
            return None
        item = series[index]
        if item is None:
            return None
        try:
            number = float(item)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    for index, stamp in enumerate(times):
        rows.append(
            HourlyComfort(
                time=stamp,
                temp_c=value("temperature_2m", index),
                apparent_c=value("apparent_temperature", index),
                humidity=value("relative_humidity_2m", index),
                uv_index=value("uv_index", index),
                rain_chance=value("precipitation_probability", index),
                wind_kmh=value("wind_speed_10m", index),
            )
        )

    return Weather(
        available=bool(rows),
        source="Open-Meteo forecast API",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        timezone=payload.get("timezone", "UTC"),
        hourly=rows,
        reason="" if rows else "Open-Meteo returned no hourly rows",
    )


def comfort_band(apparent_c: float | None) -> str:
    if apparent_c is None:
        return "unknown"
    if apparent_c < 18:
        return "cool"
    if apparent_c < 26:
        return "mild"
    if apparent_c < 32:
        return "warm"
    if apparent_c < 38:
        return "hot"
    return "severe"


def best_windows(hours: list[HourlyComfort], limit: int = 3) -> list[dict]:
    """Return the coolest daylight hours with low rain chance."""
    scored = []
    for hour in hours:
        if hour.apparent_c is None:
            continue
        uv = hour.uv_index or 0.0
        rain = hour.rain_chance or 0.0
        scored.append((hour.apparent_c + rain * 0.05 + uv * 0.15, hour))
    scored.sort(key=lambda item: item[0])
    out = []
    for _, hour in scored[:limit]:
        out.append(
            {
                "time": hour.time,
                "apparentC": hour.apparent_c,
                "uvIndex": hour.uv_index,
                "band": comfort_band(hour.apparent_c),
            }
        )
    return out