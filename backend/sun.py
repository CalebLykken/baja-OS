"""Where the sun is, for dimming the screen after dark: NOAA's general
solar position equations, good to a minute or so, with no internet. Also
sunrise and sunset, solar noon and the golden hour for the UI to show."""

import math
from datetime import datetime, timedelta, timezone

HORIZON = -0.833  # sunrise/sunset: atmospheric refraction plus the sun's radius
GOLDEN_LOW = -4.0  # golden hour: the sun between these two heights, in degrees
GOLDEN_HIGH = 6.0


def _solar(when):
    """(equation of time in minutes, declination in radians) for a UTC datetime."""
    doy = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    return eqtime, decl


def altitude(lat, lon, when=None):
    """The sun's height above the horizon in degrees (negative after sunset)."""
    when = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    eqtime, decl = _solar(when)
    minutes = when.hour * 60 + when.minute + when.second / 60 + eqtime + 4 * lon
    ha = math.radians(minutes / 4 - 180)
    la = math.radians(lat)
    cos_zenith = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))


def crossings(lat, lon, degrees, day=None):
    """(morning, evening) as UTC datetimes when the sun's centre is at
    `degrees` above the horizon on the local date `day`, or (None, None)
    when it never gets to that height that day."""
    day = day or datetime.now().astimezone().date()
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    eqtime, decl = _solar(noon)
    la = math.radians(lat)
    cos_ha = (math.cos(math.radians(90 - degrees)) / (math.cos(la) * math.cos(decl))
              - math.tan(la) * math.tan(decl))
    if not -1 <= cos_ha <= 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    morning = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    evening = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return morning, evening


def rise_set(lat, lon, day=None):
    """(sunrise, sunset) as UTC datetimes for the local date `day`, or None
    for either when the sun doesn't rise or set (far north or south)."""
    return crossings(lat, lon, HORIZON, day)


def solar_noon(lat, lon, day=None):
    """The UTC datetime when the sun is highest on the local date `day`.
    `lat` is only there so the signature matches the others."""
    day = day or datetime.now().astimezone().date()
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    eqtime, _ = _solar(noon)
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return midnight + timedelta(minutes=720 - 4 * lon - eqtime)


def golden_hour(lat, lon, day=None):
    """((morning_start, morning_end), (evening_start, evening_end)) as UTC
    datetimes, the sun between GOLDEN_LOW and GOLDEN_HIGH degrees. A value
    is None when the sun never gets that high/low today."""
    low_am, low_pm = crossings(lat, lon, GOLDEN_LOW, day)
    high_am, high_pm = crossings(lat, lon, GOLDEN_HIGH, day)
    return (low_am, high_am), (high_pm, low_pm)
