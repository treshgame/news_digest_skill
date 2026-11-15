#!/usr/bin/env python3
"""Render a digest JSON into one printable HTML page.

  render.py data/digest-2026-11-08_2026-11-14.json -o digests/2026-11-08_2026-11-14.html
  render.py ... --template other.html    (default: template.html)

Without -o the page goes to stdout.
"""
import argparse
import json
import sys
from datetime import date
from html import escape
from pathlib import Path

from common import CATEGORIES, ROOT, fail, load_feeds, period_bounds


def format_day(day: date | str) -> str:
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"


def format_period(first: date, last: date) -> str:
    """"Sat 14 Nov 2026" for one day, "Sun 8 Nov – Sat 14 Nov 2026 · 7 days" for several."""
    if first == last:
        return f"{format_day(last)} {last.year}"
    start = format_day(first) + (f" {first.year}" if first.year != last.year else "")
    return f"{start} – {format_day(last)} {last.year} · {(last - first).days + 1} days"


def render_story(story: dict) -> str:
    explanation = f"<p>{escape(story['explanation'])}</p>" if story["explanation"] else ""
    return (f'<article><h4><a href="{escape(story["link"], quote=True)}">{escape(story["title"])}</a>'
            f' <span class="day">{format_day(story["date"])}</span></h4>{explanation}</article>')


def render_region(region: str, stories: list[dict]) -> str:
    columns = []
    for category in CATEGORIES:
        in_category = sorted((s for s in stories if s["category"] == category), key=lambda s: s["date"], reverse=True)
        if in_category:
            columns.append(f'<div class="cat"><h3>{category.capitalize()}</h3>'
                           f'{"".join(render_story(s) for s in in_category)}</div>')
    return f'<section class="region"><h2>{escape(region)}</h2><div class="cats">{"".join(columns)}</div></section>'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("-o", "--output")
    parser.add_argument("--template", default="template.html", help="template file in the project folder")
    args = parser.parse_args()

    path = Path(args.json_path)
    stories = json.loads(path.read_text())
    try:
        period_label = format_period(*period_bounds(path.stem.removeprefix("digest-")))
    except ValueError:
        days = sorted(s["date"] for s in stories)  # renamed file: fall back to the stories' dates
        period_label = format_period(date.fromisoformat(days[0]), date.fromisoformat(days[-1])) if days else ""
    if not stories:
        fail("the digest has no stories")

    regions = (render_region(r, [s for s in stories if s["region"] == r]) for r in load_feeds()
               if any(s["region"] == r for s in stories))
    page = ((ROOT / args.template).read_text()
            .replace("{{PERIOD}}", escape(period_label))
            .replace("{{BODY}}", "".join(regions)))

    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page)
        print(f"wrote {output}")
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
