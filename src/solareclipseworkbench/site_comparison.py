"""Compare candidate observing sites for one eclipse.

For a short list of places this gives, side by side, what decides where to go:
how long totality lasts (with the lunar limb correction when the limb profile
is installed), how high the Sun stands at maximum eclipse, and how the
Baily's beads windows fall around C2 and C3.  Optionally the cloud cover at
maximum eclipse is fetched from Open-Meteo (https://open-meteo.com): a
forecast from about two weeks before the eclipse, or, for an eclipse in the
past, the ERA5 reanalysis of what the sky really was.

Nothing here needs Qt or a camera, so ``sew --compare`` and the
``Compare sites`` window share it.
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple

LOGGER = logging.getLogger("SEW")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo forecasts reach 16 days ahead (today + 15).  For the past, the
# forecast API accepts dates up to three months back but no longer has cloud
# cover for them, so anything older than a few days comes from the ERA5
# archive (which itself lags about five days behind).
FORECAST_DAYS_AHEAD = 15
FORECAST_DAYS_BACK = 5

CLOUD_VARIABLES = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")


@dataclass
class Site:
    """A candidate observing site."""
    name: str
    longitude: float
    latitude: float
    altitude: float

    def to_dict(self) -> dict:
        return {"name": self.name, "longitude": self.longitude, "latitude": self.latitude,
                "altitude": self.altitude}

    @classmethod
    def from_dict(cls, data: dict) -> "Site":
        return cls(str(data.get("name", "")), float(data["longitude"]), float(data["latitude"]),
                   float(data.get("altitude", 0.0)))


@dataclass
class BeadsWindow:
    """The Baily's beads window around C2 or C3, in seconds from that (limb-corrected) contact.

    ``status`` is ``solved``, ``unresolved`` (the window does not close at this
    place) or ``unavailable`` (no limb profile, or no totality).
    """
    status: str
    start: Optional[float] = None
    end: Optional[float] = None

    @property
    def length(self) -> Optional[float]:
        if self.start is None or self.end is None:
            return None
        return self.end - self.start

    def describe(self, contact: str) -> str:
        if self.status == "solved":
            return f"{contact}{self.start:+.1f} s to {contact}{self.end:+.1f} s ({self.length:.1f} s)"
        if self.status == "unresolved":
            return "unresolved"
        return "-"


@dataclass
class SiteResult:
    """The local circumstances of the eclipse at one site."""
    site: Site
    eclipse_type: str = ""
    magnitude: float = 0.0
    totality: Optional[datetime.timedelta] = None
    totality_mean: Optional[datetime.timedelta] = None
    c1_utc: Optional[datetime.datetime] = None
    c2_utc: Optional[datetime.datetime] = None
    c2_local: Optional[datetime.datetime] = None
    max_utc: Optional[datetime.datetime] = None
    max_local: Optional[datetime.datetime] = None
    c4_utc: Optional[datetime.datetime] = None
    sun_altitude: Optional[float] = None
    sun_azimuth: Optional[float] = None
    beads: dict = field(default_factory=lambda: {"C2": BeadsWindow("unavailable"),
                                                 "C3": BeadsWindow("unavailable")})
    error: Optional[str] = None

    @property
    def is_total(self) -> bool:
        return self.totality is not None

    @property
    def limb_corrected(self) -> bool:
        return self.totality_mean is not None


@dataclass
class CloudForecast:
    """Cloud cover at maximum eclipse [%], with the hourly total cover from C1 to C4."""
    total: Optional[float] = None
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    source: str = ""
    hourly: List[Tuple[datetime.datetime, Optional[float]]] = field(default_factory=list)
    error: Optional[str] = None

    def describe(self) -> str:
        if self.error:
            return self.error
        if self.total is None:
            return "-"
        layers = ", ".join(f"{name} {value:.0f}%" for name, value in
                           (("low", self.low), ("mid", self.mid), ("high", self.high)) if value is not None)
        return f"{self.total:.0f}%" + (f" ({layers})" if layers else "")


def site_result(site: Site, reference_moments: dict, magnitude: float, eclipse_type: str) -> SiteResult:
    """Summarise the output of ``calculate_reference_moments()`` for one site."""
    result = SiteResult(site, eclipse_type=eclipse_type, magnitude=float(magnitude or 0.0))
    moments = reference_moments or {}

    def utc(name):
        info = moments.get(name)
        return getattr(info, "time_utc", None)

    result.c1_utc = utc("C1")
    result.c4_utc = utc("C4")
    maximum = moments.get("MAX")
    if maximum is not None and eclipse_type != "No eclipse":
        result.max_utc = maximum.time_utc
        result.max_local = maximum.time_local
        result.sun_altitude = maximum.apparent_altitude
        result.sun_azimuth = maximum.azimuth

    if "C2" in moments and "C3" in moments:
        result.c2_utc = moments["C2"].time_utc
        result.c2_local = moments["C2"].time_local
        result.totality = moments.get("duration", moments["C3"].time_utc - moments["C2"].time_utc)
        result.totality_mean = moments.get("duration_mean")

        for contact in ("C2", "C3"):
            status = moments.get(f"BEADS_{contact}_STATUS")
            if status == "solved":
                reference = moments[contact].time_utc
                start = (moments[f"BEADS_{contact}_START"].time_utc - reference).total_seconds()
                end = (moments[f"BEADS_{contact}_END"].time_utc - reference).total_seconds()
                result.beads[contact] = BeadsWindow("solved", start, end)
            elif status:
                result.beads[contact] = BeadsWindow(str(status))
    return result


def compare_site(site: Site, date: str) -> SiteResult:
    """Compute the circumstances of the eclipse of ``date`` (YYYY-MM-DD) at one site; errors end up in the result."""
    from astropy.time import Time
    from solareclipseworkbench.reference_moments import calculate_reference_moments

    try:
        moments, magnitude, eclipse_type = calculate_reference_moments(site.longitude, site.latitude,
                                                                       site.altitude, Time(date))
    except Exception as exc:
        LOGGER.exception("Could not compute the eclipse at %s", site.name)
        return SiteResult(site, error=str(exc))
    return site_result(site, moments, magnitude, eclipse_type)


def compare_sites(sites: Iterable[Site], date: str,
                  progress: Optional[Callable[[int, SiteResult], None]] = None) -> List[SiteResult]:
    """Compute every site in turn; ``progress(index, result)`` is called after each one."""
    results = []
    for index, site in enumerate(sites):
        result = compare_site(site, date)
        results.append(result)
        if progress is not None:
            progress(index, result)
    return results


def best_totality(results: Iterable[SiteResult]) -> Optional[datetime.timedelta]:
    """The longest totality of these results, or None when none of them is total."""
    durations = [r.totality for r in results if r.totality is not None]
    return max(durations) if durations else None


# ---------------------------------------------------------------------------
# Cloud cover
# ---------------------------------------------------------------------------

def _hour_floor(moment: datetime.datetime) -> datetime.datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def forecast_source(moment_utc: datetime.datetime, today: Optional[datetime.date] = None):
    """Which Open-Meteo service covers this moment: ``(url, label)``, or ``(None, reason)`` when none does yet."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    day = moment_utc.date()
    if day > today + datetime.timedelta(days=FORECAST_DAYS_AHEAD):
        first = day - datetime.timedelta(days=FORECAST_DAYS_AHEAD)
        return None, f"no forecast yet (from {first.isoformat()})"
    if day < today - datetime.timedelta(days=FORECAST_DAYS_BACK):
        return ARCHIVE_URL, "ERA5 archive"
    return FORECAST_URL, "forecast"


def parse_cloud_cover(data: dict, moment_utc: datetime.datetime,
                      start_utc: Optional[datetime.datetime] = None,
                      end_utc: Optional[datetime.datetime] = None, source: str = "") -> CloudForecast:
    """Interpolate an Open-Meteo hourly answer (timezone UTC) to ``moment_utc``.

    The hourly total cover from ``start_utc`` to ``end_utc`` (e.g. C1 to C4) is
    kept for a closer look.
    """
    if data.get("error"):
        return CloudForecast(source=source, error=str(data.get("reason", "Open-Meteo error")))
    hourly = data.get("hourly") or {}
    times = [datetime.datetime.fromisoformat(t).replace(tzinfo=datetime.timezone.utc)
             for t in hourly.get("time", [])]
    if not times:
        return CloudForecast(source=source, error="no hourly data")

    moment = moment_utc.astimezone(datetime.timezone.utc)

    def at(variable: str) -> Optional[float]:
        values = hourly.get(variable)
        if not values:
            return None
        before = _hour_floor(moment)
        after = before + datetime.timedelta(hours=1)
        if before not in times:
            return None
        v0 = values[times.index(before)]
        v1 = values[times.index(after)] if after in times else None
        if v0 is None:
            return v1
        if v1 is None:
            return float(v0)
        fraction = (moment - before).total_seconds() / 3600.0
        return float(v0) + (float(v1) - float(v0)) * fraction

    forecast = CloudForecast(at("cloud_cover"), at("cloud_cover_low"), at("cloud_cover_mid"),
                             at("cloud_cover_high"), source=source)
    if forecast.total is None:
        forecast.error = "no cloud cover for this hour"

    first = _hour_floor((start_utc or moment).astimezone(datetime.timezone.utc))
    last = (end_utc or moment).astimezone(datetime.timezone.utc)
    totals = hourly.get("cloud_cover") or []
    forecast.hourly = [(t, totals[i] if i < len(totals) else None)
                       for i, t in enumerate(times) if first <= t <= last + datetime.timedelta(hours=1)]
    return forecast


def fetch_cloud_cover(latitude: float, longitude: float, moment_utc: datetime.datetime,
                      start_utc: Optional[datetime.datetime] = None, end_utc: Optional[datetime.datetime] = None,
                      today: Optional[datetime.date] = None, get=None, timeout: float = 15) -> CloudForecast:
    """The Open-Meteo cloud cover at ``moment_utc`` for this place (never raises: problems end up in ``error``)."""
    url, source = forecast_source(moment_utc, today)
    if url is None:
        return CloudForecast(error=source)
    if get is None:
        import requests
        get = requests.get

    first_day = (start_utc or moment_utc).astimezone(datetime.timezone.utc).date()
    last_day = ((end_utc or moment_utc).astimezone(datetime.timezone.utc) + datetime.timedelta(hours=1)).date()
    params = {"latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}",
              "hourly": ",".join(CLOUD_VARIABLES), "timezone": "UTC",
              "start_date": first_day.isoformat(), "end_date": last_day.isoformat()}
    def fetch(service_url: str, label: str) -> CloudForecast:
        try:
            response = get(service_url, params=params, timeout=timeout)
            data = response.json()
        except Exception as exc:
            LOGGER.warning("Could not fetch the cloud cover for %.4f, %.4f: %s", latitude, longitude, exc)
            return CloudForecast(source=label, error=f"no connection ({exc.__class__.__name__})")
        return parse_cloud_cover(data, moment_utc, start_utc, end_utc, label)

    forecast = fetch(url, source)
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    if forecast.total is None and url == FORECAST_URL and moment_utc.date() < today:
        # A past day the forecast no longer covers: the archive may already have it
        archived = fetch(ARCHIVE_URL, "ERA5 archive")
        if archived.total is not None:
            return archived
    return forecast


def fetch_cloud_cover_for(result: SiteResult, **kwargs) -> CloudForecast:
    """The cloud cover at maximum eclipse for a computed site."""
    if result.error or result.max_utc is None:
        return CloudForecast(error="no eclipse")
    return fetch_cloud_cover(result.site.latitude, result.site.longitude, result.max_utc,
                             result.c1_utc, result.c4_utc, **kwargs)


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def format_duration(duration: Optional[datetime.timedelta]) -> str:
    if duration is None:
        return "-"
    seconds = duration.total_seconds()
    return f"{int(seconds // 60)}m{seconds % 60:04.1f}s"


def describe_totality(result: SiteResult, best: Optional[datetime.timedelta] = None) -> str:
    if result.error:
        return "error"
    if result.totality is None:
        return f"none ({result.eclipse_type.lower()}, mag. {result.magnitude:.3f})" \
            if result.eclipse_type and result.eclipse_type != "No eclipse" else "no eclipse"
    text = format_duration(result.totality)
    if best is not None and result.totality < best:
        text += f" ({(result.totality - best).total_seconds():+.1f} s)"
    return text


def describe_sun(result: SiteResult) -> str:
    if result.sun_altitude is None:
        return "-"
    return f"{result.sun_altitude:.1f}° (az. {result.sun_azimuth:.0f}°)"


def format_comparison(results: List[SiteResult], date: str,
                      forecasts: Optional[List[Optional[CloudForecast]]] = None) -> str:
    """A plain-text table of the sites, longest totality first."""
    best = best_totality(results)
    order = sorted(range(len(results)), key=lambda i: -(results[i].totality or datetime.timedelta(0)).total_seconds())
    headers = ["Site", "Totality", "C2 (local)", "Sun at MAX", "Beads C2", "Beads C3"]
    if forecasts is not None:
        headers.append("Cloud cover at MAX")
    rows = []
    for i in order:
        r = results[i]
        row = [r.site.name,
               describe_totality(r, best),
               r.c2_local.strftime("%H:%M:%S %Z") if r.c2_local else "-",
               describe_sun(r),
               r.beads["C2"].describe("C2"),
               r.beads["C3"].describe("C3")]
        if forecasts is not None:
            forecast = forecasts[i] if i < len(forecasts) else None
            row.append(forecast.describe() if forecast else "-")
        rows.append(row)

    widths = [max(len(headers[c]), *(len(row[c]) for row in rows)) if rows else len(headers[c])
              for c in range(len(headers))]
    lines = [f"Candidate sites for the eclipse of {date}", ""]
    lines.append("  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip())
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(v.ljust(w) for v, w in zip(row, widths)).rstrip())

    notes = []
    for i in order:
        r = results[i]
        if r.error:
            notes.append(f"{r.site.name}: {r.error}")
    if results and not any(r.limb_corrected for r in results if r.is_total) and any(r.is_total for r in results):
        notes.append("Totality is for the mean lunar limb: the limb profile is not installed or switched off.")
    if forecasts is not None:
        sources = sorted({f.source for f in forecasts if f and f.source and not f.error})
        if sources:
            notes.append(f"Cloud cover: Open-Meteo {', '.join(sources)}, interpolated to maximum eclipse.")
    if notes:
        lines.append("")
        lines.extend(notes)
    return "\n".join(lines)
