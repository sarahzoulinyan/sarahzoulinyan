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
    monthly: dict[str, int] = defaultdict(int)
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
                monthly[day["date"][:7]] += day["contributionCount"]

    points: list[tuple[str, int]] = []
    for year in years:
        final_month = today.month if year == today.year else 12
        for month in range(1, final_month + 1):
            key = f"{year}-{month:02d}"
            points.append((key, monthly[key]))
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
        path.append(
            f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f}"
        )
    return " ".join(path)


def generate_svg(username: str, monthly: list[tuple[str, int]], yearly: dict[int, int]) -> str:
    width, height = 1400, 650
    left, right, top, bottom = 105, 45, 125, 145
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_value, tick_step = nice_scale(max((value for _, value in monthly), default=0))
    x_step = plot_width / max(1, len(monthly) - 1)

    coordinates: list[tuple[float, float]] = []
    for index, (_, value) in enumerate(monthly):
        x = left + index * x_step
        y = top + plot_height - (value / max_value * plot_height)
        coordinates.append((x, y))

    line = smooth_path(coordinates)
    area = f"{line} L {coordinates[-1][0]:.1f},{top + plot_height} L {coordinates[0][0]:.1f},{top + plot_height} Z"
    years = sorted(yearly)
    year_range = f"{years[0]}–{years[-1]}"
    total = sum(yearly.values())
    updated = dt.date.today().isoformat()

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{username} all-time GitHub contribution history</title>',
        f'<desc id="desc">Monthly contribution line graph covering {year_range}, automatically updated from GitHub.</desc>',
        "<defs>",
        '<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0969da" stop-opacity="0.32"/><stop offset="1" stop-color="#0969da" stop-opacity="0.03"/></linearGradient>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#1f2328" flood-opacity="0.10"/></filter>',
        "</defs>",
        '<rect x="8" y="8" width="1384" height="634" rx="20" fill="#ffffff" stroke="#d0d7de" filter="url(#shadow)"/>',
        f'<text x="700" y="54" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="31" font-weight="700" fill="#0969da">{username}\'s All-Time Contribution Graph</text>',
        f'<text x="700" y="84" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="16" fill="#57606a">Monthly GitHub contributions · {year_range}</text>',
    ]

    for value in range(0, max_value + 1, tick_step):
        y = top + plot_height - (value / max_value * plot_height)
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#b6d4fe" stroke-width="1" stroke-dasharray="4 5"/>')
        svg.append(f'<text x="{left - 16}" y="{y + 5:.1f}" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="15" font-weight="600" fill="#0969da">{value}</text>')

    for index, (label, _) in enumerate(monthly):
        if label.endswith("-01"):
            x = left + index * x_step
            svg.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#d8e8ff" stroke-width="1"/>')
            svg.append(f'<text x="{x:.1f}" y="{top + plot_height + 31}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14" font-weight="700" fill="#0969da">{label[:4]}</text>')

    svg.extend(
        [
            f'<path d="{area}" fill="url(#area)"/>',
            f'<path d="{line}" fill="none" stroke="#0969da" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
        ]
    )
    for x, y in coordinates:
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.7" fill="#1f2328"/>')

    svg.extend(
        [
            f'<text x="{left + plot_width / 2:.1f}" y="{height - 66}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#0969da">Years</text>',
            f'<text x="29" y="{top + plot_height / 2:.1f}" text-anchor="middle" transform="rotate(-90 29 {top + plot_height / 2:.1f})" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#0969da">Monthly contributions</text>',
            f'<text x="700" y="{height - 31}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="14" fill="#57606a">{len(years)} years · {total:,} contributions · Updated {updated}</text>',
            "</svg>",
        ]
    )
    return "\n".join(svg) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    monthly, yearly = get_history(args.username)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate_svg(args.username, monthly, yearly), encoding="utf-8")
    print(f"Generated {args.output} for {min(yearly)}–{max(yearly)}")


if __name__ == "__main__":
    main()
