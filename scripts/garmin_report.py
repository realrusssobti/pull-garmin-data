#!/usr/bin/env python3
"""Fetch Garmin data and generate a portable HTML health and training report."""

import datetime as dt
import html
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import garmin_pull as api

VERSION = "1.0.0"
ASSETS = Path(__file__).resolve().parents[1] / "assets"
METRICS = [
    ("sleepHours", "Nightly sleep", "h"),
    ("sleepScore", "Sleep score", "points"),
    ("restingHeartRate", "Resting heart rate", "bpm"),
    ("hrvMs", "Overnight HRV", "ms"),
    ("wakeBattery", "Waking Body Battery", "points"),
    ("stress", "Daily stress", "points"),
    ("steps", "Daily steps", "steps"),
]
CDC = "https://www.cdc.gov/sleep/about/"
HRV_GUIDE = "https://www.garmin.com/en-US/blog/fitness/understanding-the-hrv-status-on-your-garmin-smartwatch/"


def number(value, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return value if value >= minimum and (maximum is None or value <= maximum) else None


def divide(value, denominator):
    return value / denominator if value is not None and denominator else None


def mean(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return statistics.mean(values) if values else None


def total(rows, field):
    values = [r.get(field) for r in rows]
    return sum(values) if all(v is not None for v in values) else None


def dates_between(start, end):
    try:
        first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        raise api.PullError("Dates must use YYYY-MM-DD.") from None
    count = (last - first).days + 1
    if count < 2 or count > 30 or count % 2:
        raise api.PullError(
            "Reports compare equal halves: choose an even number of days from 2 to 30."
        )
    return [(first + dt.timedelta(days=i)).isoformat() for i in range(count)]


def resolve_window(days=14, end_date=None, timezone=None, now=None):
    try:
        zone = ZoneInfo(timezone) if timezone else None
    except (ZoneInfoNotFoundError, ValueError):
        raise api.PullError(
            "Unknown time zone; use an IANA name such as America/Los_Angeles."
        ) from None
    current = now or dt.datetime.now(dt.timezone.utc)
    local = current.astimezone(zone)
    end = end_date or (local.date() - dt.timedelta(days=1)).isoformat()
    try:
        start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
    except (ValueError, TypeError, OverflowError):
        raise api.PullError("Invalid report date range.") from None
    dates_between(start, end)
    return start, end, timezone or f"System local ({local.tzname()})"


def fetch_bundle(client, start, end, timezone):
    dates = dates_between(start, end)
    bundle = {
        "schema_version": 1,
        "start_date": start,
        "end_date": end,
        "timezone": timezone,
        "resources": {},
        "errors": [],
    }
    jobs = [("activities", None), ("hrv", None)]
    jobs += [
        (resource, date)
        for resource in ("daily", "sleep", "heart-rate")
        for date in dates
    ]
    for resource, date in jobs:
        args = SimpleNamespace(
            resource=resource,
            start_date=start,
            end_date=end,
            date=date,
            page_size=99,
            max_pages=20,
        )
        data, meta = api.collect(client, args)
        bundle["resources"].setdefault(resource, []).append(
            {"requested_date": date, "data": data, "metadata": meta}
        )
    bundle["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return bundle


def normalize(bundle):
    """Project only report fields; retain missingness and coverage explicitly."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("resources"), dict):
        raise api.PullError("Expected a Garmin report bundle with a resources object.")
    dates = dates_between(bundle.get("start_date"), bundle.get("end_date"))
    if bundle.get("schema_version", 1) != 1:
        raise api.PullError("Unsupported bundle schema version.")
    resources, indexed, warnings = bundle["resources"], {}, []
    if bundle.get("errors"):
        warnings.append(
            "The saved pull contains errors; only available records are shown."
        )
    for resource in ("daily", "sleep", "heart-rate"):
        indexed[resource] = {}
        for entry in resources.get(resource, []):
            date, record = entry.get("requested_date"), entry.get("data")
            if date not in dates or date in indexed[resource]:
                raise api.PullError("Duplicate or out-of-range daily response.")
            if record is not None and not isinstance(record, dict):
                raise api.PullError("Unexpected daily response schema.")
            record = record or {}
            if record.get("calendarDate") not in (None, date):
                raise api.PullError(
                    "A returned calendar date differs from its requested date."
                )
            indexed[resource][date] = record
    hrv = {}
    for entry in resources.get("hrv", []):
        record = entry.get("data")
        if record is None:
            continue
        if not isinstance(record, dict) or not isinstance(
            record.get("hrvSummaries"), list
        ):
            raise api.PullError("Unexpected HRV response schema.")
        for item in record["hrvSummaries"]:
            date = item.get("calendarDate")
            if date not in dates or date in hrv:
                raise api.PullError("Duplicate or out-of-range HRV date.")
            hrv[date] = item
    activity_entries = resources.get("activities", [])
    if len(activity_entries) > 1:
        raise api.PullError("Expected one collected activity-search result.")
    entry = activity_entries[0] if activity_entries else {}
    complete = entry.get("metadata", {}).get("complete") is True
    raw_activities = entry.get("data", [])
    if not isinstance(raw_activities, list):
        raise api.PullError("Expected an activity array.")
    activities, seen, undated = [], set(), 0
    for raw in raw_activities:
        identity = raw.get("activityId")
        if type(identity) is not int or identity <= 0 or identity in seen:
            raise api.PullError("Duplicate or invalid activity ID.")
        seen.add(identity)
        start = raw.get("startTimeLocal")
        date = start[:10] if isinstance(start, str) and start else None
        if date is not None and date not in dates:
            raise api.PullError("An activity-local date is outside the report window.")
        if date is None:
            undated += 1
        kind = (raw.get("activityType") or {}).get("typeKey", "unknown")
        minutes, km = (
            divide(number(raw.get("duration")), 60),
            divide(number(raw.get("distance")), 1000),
        )
        suspicious = (
            kind in ("running", "treadmill_running")
            and minutes is not None
            and minutes >= 10
            and km is not None
            and km < 0.1
        )
        activity = {
            "date": date,
            "time": start[11:16] if date else "",
            "type": kind,
            "sport": kind.replace("_", " ").title(),
            "minutes": minutes,
            "distanceKm": km,
            "averageHeartRate": number(raw.get("averageHR"), 1),
            "maxHeartRate": number(raw.get("maxHR"), 1),
            "exerciseLoad": number(raw.get("activityTrainingLoad")),
            "aerobicEffect": number(raw.get("aerobicTrainingEffect")),
            "anaerobicEffect": number(raw.get("anaerobicTrainingEffect")),
            "elevationGainM": number(raw.get("elevationGain")),
            "benefit": str(raw.get("trainingEffectLabel") or "Unknown")
            .replace("_", " ")
            .title()
            .replace("Vo2Max", "VO₂ max"),
            "distanceFlagged": suspicious,
        }
        activity["paceMinKm"] = (
            divide(minutes, km) if kind == "running" and not suspicious else None
        )
        activities.append(activity)
    activities.sort(key=lambda a: (a["date"] or "", a["time"]))
    dated_complete = complete and not undated
    if not complete:
        warnings.append(
            "Activity search is incomplete. Period totals and training comparisons are unavailable; the log shows retrieved records only."
        )
    if undated:
        warnings.append(
            f"{undated} activities have no local date. They remain in the log; period training totals are unavailable."
        )
    flagged = sum(a["distanceFlagged"] for a in activities)
    if flagged:
        warnings.append(
            f"{flagged} running records contain under 100 m over at least 10 minutes. Their duration remains in exercise time; distance and pace are excluded from outdoor-run comparisons."
        )
    if any(a["minutes"] is None or a["exerciseLoad"] is None for a in activities):
        warnings.append(
            "Some activities are missing duration or exercise load; affected totals are unavailable."
        )
    daily, rhr_mismatch = [], 0
    for date in dates:
        d, s, h = (
            indexed[name].get(date, {}) for name in ("daily", "sleep", "heart-rate")
        )
        nightly = hrv.get(date, {})
        d_rhr, h_rhr = (
            number(d.get("restingHeartRate"), 1),
            number(h.get("restingHeartRate"), 1),
        )
        if d_rhr is not None and h_rhr is not None and d_rhr != h_rhr:
            rhr_mismatch += 1
        rows = [a for a in activities if a["date"] == date]
        daily.append(
            {
                "date": date,
                "steps": number(d.get("totalSteps")),
                "restingHeartRate": d_rhr if d_rhr is not None else h_rhr,
                "hrvMs": number(nightly.get("lastNightAvg"), 1),
                "hrvBaselineAvailable": isinstance(nightly.get("baseline"), dict)
                and bool(nightly["baseline"]),
                "hrvStatus": str(nightly.get("status") or "Unavailable"),
                "sleepHours": divide(number(s.get("sleepTimeSeconds")), 3600),
                "napMinutes": divide(number(s.get("napTimeSeconds")), 60),
                "sleepScore": number(
                    (s.get("sleepScores") or {}).get("overall", {}).get("value"), 0, 100
                ),
                "sleepStress": number(s.get("avgSleepStress"), 0, 100),
                "stress": number(d.get("averageStressLevel"), 0, 100),
                "wakeBattery": number(d.get("bodyBatteryAtWakeTime"), 0, 100),
                "lowBattery": number(d.get("bodyBatteryLowestValue"), 0, 100),
                "activityCount": len(rows) if dated_complete else None,
                "activityMinutes": total(rows, "minutes") if dated_complete else None,
                "exerciseLoad": total(rows, "exerciseLoad") if dated_complete else None,
            }
        )
    if rhr_mismatch:
        warnings.append(
            f"Resting HR differs between endpoints on {rhr_mismatch} days; the daily-summary reading is used, with heart-rate readings as fallback only when missing."
        )
    periods = []
    half = len(daily) // 2
    for rows in (daily[:half], daily[half:]):
        aset = [
            a
            for a in activities
            if a["date"] and rows[0]["date"] <= a["date"] <= rows[-1]["date"]
        ]
        runs = [a for a in aset if a["type"] == "running" and not a["distanceFlagged"]]
        row = {
            "start": rows[0]["date"],
            "end": rows[-1]["date"],
            "days": len(rows),
            "sessions": len(aset) if dated_complete else None,
            "activeDays": sum(d["activityCount"] > 0 for d in rows)
            if dated_complete
            else None,
            "activityMinutes": total(aset, "minutes") if dated_complete else None,
            "exerciseLoad": total(aset, "exerciseLoad") if dated_complete else None,
            "runningKm": total(runs, "distanceKm") if dated_complete else None,
            "runningMinutes": total(runs, "minutes") if dated_complete else None,
            "runningSessions": len(runs) if dated_complete else None,
        }
        row["paceMinKm"] = divide(row["runningMinutes"], row["runningKm"])
        row["coverage"] = {
            key: sum(d[key] is not None for d in rows) for key, _, _ in METRICS
        }
        row.update({key: mean(rows, key) for key, _, _ in METRICS})
        periods.append(row)
    coverage = {key: sum(d[key] is not None for d in daily) for key, _, _ in METRICS}
    if any(count < len(daily) for count in coverage.values()):
        warnings.append(
            "Some daily metrics are missing. Averages use available days; sample counts appear beside incomplete averages, and recovery comparisons require both full periods."
        )
    return {
        "generatorVersion": VERSION,
        "start": dates[0],
        "end": dates[-1],
        "timezone": str(bundle.get("timezone", "Not supplied")),
        "retrievedAt": str(bundle.get("retrieved_at", "Not supplied")),
        "synthetic": bundle.get("synthetic") is True,
        "daily": daily,
        "activities": activities,
        "periods": periods,
        "coverage": coverage,
        "activityComplete": dated_complete,
        "warnings": warnings,
    }


def fmt(value, digits=1):
    return "—" if value is None else f"{value:,.{digits}f}"


def hours(value):
    if value is None:
        return "—"
    minutes = round(value * 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def pace(value):
    if value is None:
        return "—"
    seconds = round(value * 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def change(first, second, percent=False, digits=1):
    if first is None or second is None or (percent and first == 0):
        return "—"
    difference = ((second / first - 1) * 100) if percent else second - first
    sign = "−" if difference < 0 else "+" if difference > 0 else ""
    return f"{sign}{abs(difference):.{digits}f}" + ("%" if percent else "")


def narrative(report):
    """Describe observations with explicit completeness checks, not a readiness score."""
    days, acts = report["daily"], report["activities"]
    first, last = report["periods"]

    def full(key):
        return all(p["coverage"][key] == p["days"] for p in (first, last))

    coverage = report["coverage"]
    training = f"{len(acts)} activities were retrieved. "
    if report["activityComplete"]:
        active = sum(d["activityCount"] > 0 for d in days)
        training += f"Recorded exercise spans {active} of {len(days)} days"
        duration = total(acts, "minutes")
        training += (
            f" and totals {hours(divide(duration, 60))}."
            if duration is not None
            else "; some activity durations are missing."
        )
        if first["activityMinutes"] is not None and last["activityMinutes"] is not None:
            training += f" Exercise time changed from {hours(first['activityMinutes'] / 60)} to {hours(last['activityMinutes'] / 60)} ({change(first['activityMinutes'], last['activityMinutes'], True)})."
        if first["exerciseLoad"] is not None and last["exerciseLoad"] is not None:
            training += f" Summed exercise load changed from {fmt(first['exerciseLoad'], 0)} to {fmt(last['exerciseLoad'], 0)} ({change(first['exerciseLoad'], last['exerciseLoad'], True)})."
    else:
        training += "Training totals cannot be established from this incomplete or undated search."
    sleep_mean, sleep_n = mean(days, "sleepHours"), coverage["sleepHours"]
    if sleep_n:
        short = sum(d["sleepHours"] is not None and d["sleepHours"] < 7 for d in days)
        sleep = f"Main sleep averaged {hours(sleep_mean)} over {sleep_n} measured nights; {short} were under seven hours."
        if full("sleepHours"):
            sleep += f" The second period changed by {change(first['sleepHours'] * 60, last['sleepHours'] * 60, digits=0)} minutes per night."
        if full("sleepScore"):
            sleep += f" Average sleep score changed from {fmt(first['sleepScore'], 0)} to {fmt(last['sleepScore'], 0)}."
        naps = total(days, "napMinutes")
        sleep += (
            f" Recorded naps totaled {hours(naps / 60)} and are excluded from these nightly averages."
            if naps is not None
            else " Nap coverage is incomplete."
        )
    else:
        sleep = "No nightly sleep duration was available for this window."
    comparisons = []
    for key, label, unit in METRICS[2:5]:
        if full(key):
            comparisons.append(
                f"{label} changed from {fmt(first[key])} to {fmt(last[key])} {unit}"
            )
    recovery = (
        "; ".join(comparisons) + "."
        if comparisons
        else "There is not enough complete daily coverage to compare recovery readings across both periods."
    )
    baselines = sum(d["hrvBaselineAvailable"] for d in days)
    if baselines == 0:
        recovery += " No personal HRV baseline was returned; no balanced/unbalanced status is inferred."
    else:
        latest = next(d for d in reversed(days) if d["hrvBaselineAvailable"])
        recovery += f" A personal HRV baseline was available on {baselines} days; the latest supplied status was {latest['hrvStatus'].replace('_', ' ').lower()} ({latest['date']})."
    recovery += " Interpret these trends alongside how rested you feel and the demands of your recent training."
    running = "No comparable outdoor-running distance/pace totals are available."
    if report["activityComplete"] and any(a["type"] == "running" for a in acts):
        running = (
            f"Outdoor running covered {fmt(first['runningKm'], 2)} km in the first period and {fmt(last['runningKm'], 2)} km in the second. "
            f"Aggregate pace was {pace(first['paceMinKm'])} versus {pace(last['paceMinKm'])} per km. "
            "Different routes, elevations, durations, and efforts can change pace; this is not a matched fitness test."
        )
    running += " Strength and climbing progression require comparable weights, repetitions, or grades, which these summaries do not provide."
    suggestions = []
    if sleep_mean is not None and sleep_mean < 7:
        suggestions.append(
            "Make sleep the first experiment: protect a consistent sleep window and track whether longer sleep improves how rested you feel. The seven-hour reference follows general adult sleep guidance."
        )
    if any(a["type"] == "running" for a in acts):
        suggestions.append(
            "For a clearer progression signal, compare a familiar run at similar effort and conditions. Track weights/repetitions or climbing grades for those activities rather than relying on session minutes."
        )
    if baselines == 0 and coverage["hrvMs"]:
        suggestions.append(
            "Continue consistent overnight wear while the personal HRV baseline develops. Compare trends alongside sleep, fatigue, and soreness rather than interpreting one night in isolation."
        )
    if report["warnings"]:
        suggestions.append(
            "Resolve the data gaps or flagged recordings before drawing conclusions from unavailable comparisons."
        )
    return {
        "training": training,
        "sleep": sleep,
        "recovery": recovery,
        "running": running,
        "suggestions": suggestions,
    }


def esc(value):
    return html.escape(str(value), quote=True)


def table(headers, rows, css="", identifier=""):
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">No records available.</td></tr>'
    return f'<div class="table-scroll"><table class="{css}" id="{identifier}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def chart(rows, fields, labels, title, unit, bars=False, zero=True, reference=None):
    """Inline SVG with explicit gaps and keyboard/pointer-accessible values."""
    values = [r.get(f) for r in rows for f in fields if r.get(f) is not None]
    if not values:
        return f'<figure class="chart"><figcaption>{esc(title)}</figcaption><p class="empty">No measurements available.</p></figure>'
    lo = 0 if zero else max(0, math.floor(min(values) - 3))
    hi = max(max(values), reference or 0)
    hi = max(lo + 1, math.ceil(hi * 1.08))
    width, height, left, right, top, bottom = 500, 285, 52, 16, 24, 42
    pw, ph = width - left - right, height - top - bottom

    def x(i):
        return left + pw * (i + 0.5) / max(1, len(rows))

    def y(v):
        return top + ph * (1 - (v - lo) / (hi - lo))

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}"><title>{esc(title)} ({esc(unit)})</title>'
    ]
    for tick in range(5):
        value = lo + (hi - lo) * tick / 4
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y(value):.2f}" y2="{y(value):.2f}" class="grid"/><text x="{left - 8}" y="{y(value) + 5:.2f}" text-anchor="end">{value:g}</text>'
        )
    parts.append(f'<text x="{left}" y="15">{esc(unit)}</text>')
    for i in range(0, len(rows), max(1, math.ceil(len(rows) / 5))):
        date = dt.date.fromisoformat(rows[i]["date"])
        parts.append(
            f'<text x="{x(i):.2f}" y="{height - 14}" text-anchor="middle">{date:%b} {date.day}</text>'
        )
    for index, field in enumerate(fields):
        color = ["var(--blue)", "var(--teal)", "var(--amber)"][index % 3]
        segment = []
        for i, row in enumerate(rows):
            value = row.get(field)
            if value is None:
                if segment:
                    parts.append(
                        f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>'
                    )
                    segment = []
                continue
            tip = esc(f"{row['date']} · {labels[index]}: {fmt(value)} {unit}")
            attributes = f'tabindex="0" data-tip="{tip}" aria-label="{tip}"'
            if bars:
                w = min(26, pw / len(rows) * 0.62)
                parts.append(
                    f'<rect x="{x(i) - w / 2:.2f}" y="{y(value):.2f}" width="{w:.2f}" height="{max(0, y(0) - y(value)):.2f}" rx="4" fill="{color}" {attributes}><title>{tip}</title></rect>'
                )
            else:
                segment.append(f"{x(i):.2f},{y(value):.2f}")
                parts.append(
                    f'<circle cx="{x(i):.2f}" cy="{y(value):.2f}" r="4" fill="{color}" {attributes}><title>{tip}</title></circle>'
                )
        if segment:
            parts.append(
                f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            )
    if reference is not None:
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y(reference):.2f}" y2="{y(reference):.2f}" class="reference"/><text x="{width - right}" y="{y(reference) - 7:.2f}" text-anchor="end" class="reference-label">{reference:g} {esc(unit)} reference</text>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{["var(--blue)", "var(--teal)", "var(--amber)"][i % 3]}"></i>{esc(label)}</span>'
        for i, label in enumerate(labels)
    )
    return f'<figure class="chart"><figcaption>{esc(title)}</figcaption>{"".join(parts)}<div class="legend">{legend}</div></figure>'


def render(report):
    first, last = report["periods"]
    days, activities = report["daily"], report["activities"]
    story = narrative(report)
    comparisons = []
    for field, label, formatter in [
        ("sessions", "Recorded sessions", lambda v: fmt(v, 0)),
        (
            "activeDays",
            "Days with a recorded session",
            lambda v: f"{fmt(v, 0)}/{first['days']}",
        ),
        ("activityMinutes", "Recorded exercise time", lambda v: hours(divide(v, 60))),
        ("exerciseLoad", "Exercise-load sum", lambda v: fmt(v, 0)),
        ("runningKm", "Outdoor running (km)", lambda v: fmt(v, 2)),
    ]:
        comparisons.append(
            [
                label,
                formatter(first[field]),
                formatter(last[field]),
                change(
                    first[field],
                    last[field],
                    field not in ("sessions", "activeDays"),
                    0 if field in ("sessions", "activeDays") else 1,
                ),
            ]
        )
    for field, label, unit in METRICS:
        cells = []
        for period in (first, last):
            value = (
                hours(period[field])
                if field == "sleepHours"
                else fmt(period[field], 0 if field == "steps" else 1)
            )
            if period["coverage"][field] != period["days"]:
                value += f" ({period['coverage'][field]}/{period['days']} days)"
            cells.append(value)
        full = all(p["coverage"][field] == p["days"] for p in (first, last))
        diff = (
            change(first[field], last[field]) + f" {unit}"
            if full
            else "Incomplete coverage"
        )
        if full and field == "sleepHours":
            diff = change(first[field] * 60, last[field] * 60, digits=0) + " min"
        comparisons.append([label, *cells, diff])
    comparison = table(
        [
            "Measure",
            f"{first['start']} – {first['end']}",
            f"{last['start']} – {last['end']}",
            "Change",
        ],
        comparisons,
        "comparison",
    )
    charts = "".join(
        [
            chart(
                days,
                ["exerciseLoad"],
                ["Exercise-load sum"],
                "Recorded exercise load",
                "points",
                bars=True,
            ),
            chart(
                days,
                ["sleepHours"],
                ["Main sleep period"],
                "Nightly sleep duration",
                "hours",
                bars=True,
                reference=7,
            ),
            chart(
                days,
                ["restingHeartRate"],
                ["Resting heart rate"],
                "Daily resting heart rate",
                "bpm",
                zero=False,
            ),
            chart(
                days,
                ["hrvMs"],
                ["Nightly average HRV"],
                "Overnight HRV",
                "ms",
                zero=False,
            ),
            chart(
                days,
                ["wakeBattery", "lowBattery"],
                ["At waking", "Daily minimum"],
                "Body Battery",
                "score",
            ),
            chart(
                days, ["steps"], ["Daily steps"], "Daily movement", "steps", bars=True
            ),
        ]
    )
    sport_rows = []
    for sport in sorted({a["sport"] for a in activities}):
        row = [sport]
        for period in (first, last):
            subset = [
                a
                for a in activities
                if a["sport"] == sport
                and a["date"]
                and period["start"] <= a["date"] <= period["end"]
            ]
            row.append(
                f"{len(subset)} sessions · {fmt(total(subset, 'minutes'), 0)} min"
                if report["activityComplete"]
                else "Incomplete search"
            )
        sport_rows.append(row)
    runs = [a for a in activities if a["type"] == "running"]
    runs_table = table(
        ["Date", "km", "Pace / km", "Avg HR", "Gain (m)", "Aerobic effect"],
        [
            [
                a["date"] or "Undated",
                fmt(a["distanceKm"], 2) + (" †" if a["distanceFlagged"] else ""),
                pace(a["paceMinKm"]),
                fmt(a["averageHeartRate"], 0),
                fmt(a["elevationGainM"], 0),
                fmt(a["aerobicEffect"]),
            ]
            for a in runs
        ],
    )
    sessions = table(
        ["Date", "Activity", "Minutes", "Avg HR", "Load", "Garmin benefit"],
        [
            [
                a["date"] or "Undated",
                a["sport"],
                fmt(a["minutes"]),
                fmt(a["averageHeartRate"], 0),
                fmt(a["exerciseLoad"]),
                a["benefit"],
            ]
            for a in reversed(activities)
        ],
        identifier="sessions",
    )
    daily_table = table(
        [
            "Date",
            "Sleep",
            "Score",
            "Resting HR",
            "HRV (ms)",
            "Waking battery",
            "Stress",
            "Steps",
        ],
        [
            [
                d["date"],
                hours(d["sleepHours"]),
                fmt(d["sleepScore"], 0),
                fmt(d["restingHeartRate"], 0),
                fmt(d["hrvMs"], 0),
                fmt(d["wakeBattery"], 0),
                fmt(d["stress"], 0),
                fmt(d["steps"], 0),
            ]
            for d in days
        ],
    )
    warning_html = (
        '<aside class="notice"><h2>Data coverage</h2><ul>'
        + "".join(f"<li>{esc(w)}</li>" for w in report["warnings"])
        + "</ul></aside>"
        if report["warnings"]
        else ""
    )
    replacements = {
        "TITLE": "Your Garmin health & training report",
        "PERIOD": f"{esc(report['start'])} — {esc(report['end'])}",
        "SUBTITLE": f"{len(days)} days · {esc(report['timezone'])} · Two equal {first['days']}-day periods",
        "DEMO": '<div class="demo-label">Synthetic demonstration · not personal Garmin data</div>'
        if report["synthetic"]
        else "",
        "SUMMARY": "".join(
            f"<li>{esc(story[k])}</li>" for k in ("training", "sleep", "recovery")
        ),
        "WARNINGS": warning_html,
        "COMPARISON": comparison,
        "CHARTS": charts,
        "TRAINING": esc(story["running"]),
        "SPORTS": table(["Activity", "First period", "Second period"], sport_rows),
        "RUNS": runs_table,
        "ACTIONS": "".join(f"<li>{esc(s)}</li>" for s in story["suggestions"])
        or "<li>Use these observations as a baseline for the next comparable period.</li>",
        "SESSIONS": sessions,
        "DAILY": daily_table,
        "COVERAGE": ", ".join(
            f"{label}: {report['coverage'][key]}/{len(days)} days"
            for key, label, _ in METRICS
        ),
        "RETRIEVED": esc(report["retrievedAt"]),
        "VERSION": VERSION,
        "DATA": json.dumps(report, ensure_ascii=True, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026"),
    }
    template = (ASSETS / "report.html").read_text()
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda match: replacements[match[1]], template)


def main(argv=None):
    parser = api.SafeArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--from-json", type=Path, help="Render a saved report bundle without API calls."
    )
    mode.add_argument(
        "--demo",
        action="store_true",
        help="Render synthetic example data without credentials.",
    )
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--key-env", metavar="NAME")
    auth.add_argument("--token-env", metavar="NAME")
    auth.add_argument("--key-stdin", action="store_true")
    auth.add_argument("--token-stdin", action="store_true")
    parser.add_argument(
        "--days", type=int, help="Even number from 2 to 30; default 14."
    )
    parser.add_argument(
        "--end-date",
        type=api.valid_date,
        help="Inclusive; defaults to yesterday in the chosen time zone.",
    )
    parser.add_argument(
        "--timezone",
        help="IANA zone, e.g. America/Los_Angeles; defaults to system local.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New HTML file in a private directory outside repositories.",
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        help="Also save a reusable raw bundle to a new private file.",
    )
    args = parser.parse_args(argv)
    client = None
    try:
        if args.output.suffix.lower() != ".html":
            raise api.PullError("Output must be an .html file.")
        output = args.output.expanduser().absolute()
        if args.save_json and args.save_json.expanduser().absolute() == output:
            raise api.PullError("HTML and JSON outputs must have different filenames.")
        api.private_destination(str(output))
        if args.save_json:
            api.private_destination(str(args.save_json.expanduser().absolute()))
        if args.from_json or args.demo:
            if any(
                [
                    args.key_env,
                    args.token_env,
                    args.key_stdin,
                    args.token_stdin,
                    args.days is not None,
                    args.end_date,
                    args.timezone,
                ]
            ):
                raise api.PullError(
                    "Offline inputs already specify dates and time zone; omit live-fetch options."
                )
            if args.from_json:
                if args.from_json.stat().st_size > 80 * 1024 * 1024:
                    raise api.PullError("Saved bundle exceeds 80 MiB.")
                bundle = json.loads(args.from_json.read_text())
            else:
                from demo_data import demo_bundle

                bundle = demo_bundle()
        else:
            start, end, zone = resolve_window(
                args.days if args.days is not None else 14, args.end_date, args.timezone
            )
            if (
                args.token_env
                or args.token_stdin
                or (
                    not args.key_env
                    and not args.key_stdin
                    and os.environ.get("GARMIN_ACCESS_TOKEN")
                )
            ):
                token = api.clean_token(
                    api.read_secret(
                        args.token_stdin, args.token_env or "GARMIN_ACCESS_TOKEN"
                    )
                )
            else:
                key = api.clean_api_key(
                    api.read_secret(args.key_stdin, args.key_env or "GARMIN_API_KEY")
                )
                try:
                    token = api.exchange_api_key(key, approved=True)
                finally:
                    key = None
            client = api.Client(token)
            token = None
            bundle = fetch_bundle(client, start, end, zone)
        report = normalize(bundle)
        api.private_output(str(output), render(report).encode(), binary=True)
        if args.save_json:
            api.private_output(str(args.save_json.expanduser().absolute()), bundle)
        print(
            json.dumps(
                {
                    "status": "partial" if report["warnings"] else "ok",
                    "output": str(output),
                    "start": report["start"],
                    "end": report["end"],
                    "activities": len(report["activities"]),
                    "warnings": len(report["warnings"]),
                    "synthetic": report["synthetic"],
                }
            )
        )
        return 0
    except api.PullError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(
            "Report generation failed: check the input schema, credentials, and output paths.",
            file=sys.stderr,
        )
        return 1
    finally:
        if client is not None:
            client._token = None


if __name__ == "__main__":
    raise SystemExit(main())
