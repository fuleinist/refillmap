from datetime import datetime, timedelta, timezone

from refillmap.solar import SunPosition, shadow_vector, solar_position

SYDNEY_LAT = -33.8688
SYDNEY_LON = 151.2093


def test_winter_noon_elevation():
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone(timedelta(hours=10)))
    sun = solar_position(SYDNEY_LAT, SYDNEY_LON, when)
    assert abs(sun.elevation - 32.7) < 1.5
    assert sun.is_day
    # The sun sits due north at noon in the southern hemisphere.
    assert sun.azimuth < 12 or sun.azimuth > 348


def test_summer_noon_elevation():
    # Solar noon in Sydney in December falls near 12:55 AEDT, not at 12:00.
    best = None
    for minute in range(0, 24 * 60, 5):
        when = datetime(2026, 12, 21, minute // 60, minute % 60, tzinfo=timezone(timedelta(hours=11)))
        sun = solar_position(SYDNEY_LAT, SYDNEY_LON, when)
        if best is None or sun.elevation > best:
            best = sun.elevation
    assert abs(best - 79.6) < 1.0


def test_night_has_negative_elevation():
    when = datetime(2026, 6, 21, 23, 0, tzinfo=timezone(timedelta(hours=10)))
    sun = solar_position(SYDNEY_LAT, SYDNEY_LON, when)
    assert sun.elevation < 0
    assert not sun.is_day


def test_azimuth_is_normalised():
    for hour in range(0, 24, 3):
        when = datetime(2026, 11, 19, hour, 0, tzinfo=timezone(timedelta(hours=11)))
        sun = solar_position(SYDNEY_LAT, SYDNEY_LON, when)
        assert 0.0 <= sun.azimuth < 360.0


def test_shadow_length_at_thirty_degrees():
    sun = SunPosition(elevation=30.0, azimuth=0.0, is_day=True)
    dx, dy = shadow_vector(sun, 10.0)
    length = (dx * dx + dy * dy) ** 0.5
    assert abs(length - 17.32) < 0.5
    # Sun in the north, so the shadow falls south.
    assert dy < 0
    assert abs(dx) < 0.01


def test_shadow_is_zero_at_night():
    sun = SunPosition(elevation=-5.0, azimuth=0.0, is_day=False)
    assert shadow_vector(sun, 20.0) == (0.0, 0.0)