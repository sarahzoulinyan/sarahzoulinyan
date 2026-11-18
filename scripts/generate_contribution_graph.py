#!/usr/bin/env python3
"""Generate an all-years GitHub contribution history SVG."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path


YEARS_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection { contributionYears }
  }
}
"""

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(query: str, **variables: str) -> dict:
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        command.extend(["-F", f"{name}={value}"])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def get_history(username: str) -> tuple[list[tuple[str, int]], dict[int, int]]:
    years_data = graphql(YEARS_QUERY, login=username)
    years = sorted(years_data["user"]["contributionsCollection"]["contributionYears"])
    today = dt.date.today()
    daily: dict[str, int] = {}
    yearly: dict[int, int] = {}

    for year in years:
        last_day = today if year == today.year else dt.date(year, 12, 31)
        data = graphql(
            CALENDAR_QUERY,
            login=username,
            **{
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{last_day.isoformat()}T23:59:59Z",
            },
        )
        contribution_calendar = data["user"]["contributionsCollection"]["contributionCalendar"]
        yearly[year] = contribution_calendar["totalContributions"]
        for week in contribution_calendar["weeks"]:
            for day in week["contributionDays"]:
                daily[day["date"]] = day["contributionCount"]

    weekly: dict[dt.date, int] = defaultdict(int)
    for date_text, count in daily.items():
        date = dt.date.fromisoformat(date_text)
        week_start = date - dt.timedelta(days=date.weekday())
        weekly[week_start] += count

    first_day = dt.date(years[0], 1, 1)
    week = first_day - dt.timedelta(days=first_day.weekday())
    final_week = today - dt.timedelta(days=today.weekday())
    points: list[tuple[str, int]] = []
    while week <= final_week:
        if weekly[week] > 0:
            points.append((week.isoformat(), weekly[week]))
        week += dt.timedelta(days=7)
    return points, yearly


def nice_scale(maximum: int) -> tuple[int, int]:
    if maximum <= 5:
        return 5, 1
    raw = maximum / 5
    magnitude = 10 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    factor = 1 if normalized <= 1 else 2 if normalized <= 2 else 5 if normalized <= 5 else 10
    step = int(factor * magnitude)
    ceiling = int(math.ceil(maximum / step) * step)
    return ceiling, step


def smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        return f"M {points[0][0]:.1f},{points[0][1]:.1f}"
    path = [f"M {points[0][0]:.1f},{points[0][1]:.1f}"]
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        low, high = sorted((p1[1], p2[1]))
        c1y = max(low, min(high, c1y))
        c2y = max(low, min(high, c2y))
        path.append(
            f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f}"
        )
    return " ".join(path)


def generate_svg(
    username: str,
    display_name: str,
    activity: list[tuple[str, int]],
    yearly: dict[int, int],
) -> str:
    width, height = 1400, 650
    left, right, top, bottom = 105, 45, 125, 145
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_value, tick_step = nice_scale(max((value for _, value in activity), default=0))
    x_step = plot_width / max(1, len(activity) - 1)

    coordinates: list[tuple[float, float]] = []
    for index, (_, value) in enumerate(activity):
        x = left + index * x_step
        y = top + plot_height - (value / max_value * plot_height)
        coordinates.append((x, y))

    line = smooth_path(coordinates)
    area = f"{line} L {coordinates[-1][0]:.1f},{top + plot_height} L {coordinates[0][0]:.1f},{top + plot_height} Z"
    years = sorted(yearly)
    total = sum(yearly.values())
    updated = dt.date.today().isoformat()

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{display_name} all-time GitHub contribution history</title>',
        f'<desc id="desc">A dense weekly contribution graph using all available GitHub activity for {username}.</desc>',
        "<defs>",
        '<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0969da" stop-opacity="0.32"/><stop offset="1" stop-color="#0969da" stop-opacity="0.03"/></linearGradient>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#1f2328" flood-opacity="0.10"/></filter>',
        "</defs>",
        '<rect x="8" y="8" width="1384" height="634" rx="20" fill="#ffffff" stroke="#d0d7de" filter="url(#shadow)"/>',
        f'<text x="700" y="54" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="31" font-weight="700" fill="#0969da">{display_name}\'s Contribution Graph</text>',
        f'<text x="700" y="84" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="16" fill="#57606a">Weekly GitHub contributions across all recorded activity</text>',
    ]

    for value in range(0, max_value + 1, tick_step):
        y = top + plot_height - (value / max_value * plot_height)
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#b6d4fe" stroke-width="1" stroke-dasharray="4 5"/>')
        svg.append(f'<text x="{left - 16}" y="{y + 5:.1f}" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="15" font-weight="600" fill="#0969da">{value}</text>')

    scale_step = max(1, len(activity) // 30)
    scale_indexes = list(range(0, len(activity), scale_step))
    if scale_indexes[-1] != len(activity) - 1:
        scale_indexes.append(len(activity) - 1)
    for index in scale_indexes:
        x = left + index * x_step
        svg.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#b6d4fe" stroke-width="1" stroke-dasharray="3 4"/>')
        svg.append(f'<text x="{x:.1f}" y="{top + plot_height + 31}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="12" font-weight="700" fill="#0969da">{index + 1}</text>')

    svg.extend(
        [
            f'<path d="{area}" fill="url(#area)"/>',
            f'<path d="{line}" fill="none" stroke="#0969da" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
        ]
    )
    for x, y in coordinates:
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.7" fill="#1f2328"/>')

    svg.extend(
        [
            f'<text x="{left + plot_width / 2:.1f}" y="{height - 66}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#0969da">Active Weeks</text>',
            f'<text x="29" y="{top + plot_height / 2:.1f}" text-anchor="middle" transform="rotate(-90 29 {top + plot_height / 2:.1f})" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#0969da">Contributions</text>',
            f'<text x="700" y="{height - 31}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14" fill="#57606a">{len(activity):,} active weeks · {total:,} contributions · Updated {updated}</text>',
            "</svg>",
        ]
    )
    return "\n".join(svg) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    activity, yearly = get_history(args.username)
    display_name = args.display_name or args.username
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        generate_svg(args.username, display_name, activity, yearly), encoding="utf-8"
    )
    print(f"Generated {args.output} with {len(activity)} weekly data points")


if __name__ == "__main__":
    main()
