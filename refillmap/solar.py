"""NOAA solar position equations. No third-party dependencies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SunPosition:
    elevation: float  # degrees above the horizon
    azimuth: float  # degrees clockwise from north
    is_day: bool


def _rad(deg: float) -> float:
    return math.radians(deg)


def julian_day(when: datetime) -> float:
    dt = when.astimezone(timezone.utc)
    year, month = dt.year, dt.month
    day = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
    )


def solar_position(lat: float, lon: float, when: datetime) -> SunPosition:
    """Return the sun position for a latitude, longitude and instant."""
    dt = when.astimezone(timezone.utc)
    jd = julian_day(dt)
    century = (jd - 2451545.0) / 36525.0

    mean_long = (280.46646 + century * (36000.76983 + century * 0.0003032)) % 360.0
    mean_anomaly = 357.52911 + century * (35999.05029 - 0.0001537 * century)
    eccentricity = 0.016708634 - century * (0.000042037 + 0.0000001267 * century)

    m_rad = _rad(mean_anomaly)
    centre = (
        math.sin(m_rad) * (1.914602 - century * (0.004817 + 0.000014 * century))
        + math.sin(2 * m_rad) * (0.019993 - 0.000101 * century)
        + math.sin(3 * m_rad) * 0.000289
    )
    true_long = mean_long + centre
    omega = 125.04 - 1934.136 * century
    apparent_long = true_long - 0.00569 - 0.00478 * math.sin(_rad(omega))

    eps0 = 23.0 + (26.0 + (21.448 - century * (46.815 + century * (0.00059 - century * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(_rad(omega))

    declination = math.degrees(math.asin(math.sin(_rad(eps)) * math.sin(_rad(apparent_long))))

    y = math.tan(_rad(eps / 2.0)) ** 2
    eq_time = 4.0 * math.degrees(
        y * math.sin(2 * _rad(mean_long))
        - 2 * eccentricity * math.sin(m_rad)
        + 4 * eccentricity * y * math.sin(m_rad) * math.cos(2 * _rad(mean_long))
        - 0.5 * y * y * math.sin(4 * _rad(mean_long))
        - 1.25 * eccentricity * eccentricity * math.sin(2 * m_rad)
    )

    minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0 + dt.microsecond / 6e7
    true_solar = (minutes + eq_time + 4.0 * lon) % 1440.0
    hour_angle = true_solar / 4.0 - 180.0

    lat_rad = _rad(lat)
    decl_rad = _rad(declination)
    ha_rad = _rad(hour_angle)
    cos_zenith = math.sin(lat_rad) * math.sin(decl_rad) + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(ha_rad)
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.degrees(math.acos(cos_zenith))
    elevation = 90.0 - zenith

    azimuth = math.degrees(
        math.atan2(
            math.sin(ha_rad),
            math.cos(ha_rad) * math.sin(lat_rad) - math.tan(decl_rad) * math.cos(lat_rad),
        )
    ) + 180.0
    azimuth %= 360.0

    return SunPosition(elevation=elevation, azimuth=azimuth, is_day=elevation > 0.0)


def shadow_vector(sun: SunPosition, height_m: float) -> tuple[float, float]:
    """Ground shadow offset (metres east, metres north) for an object height."""
    if not sun.is_day or sun.elevation <= 0.0:
        return (0.0, 0.0)
    elevation = max(sun.elevation, 2.0)
    length = height_m / math.tan(_rad(elevation))
    bearing = _rad((sun.azimuth + 180.0) % 360.0)
    return (length * math.sin(bearing), length * math.cos(bearing))