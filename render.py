#!/usr/bin/env python3
"""Render a digest JSON into one printable HTML page.

  render.py data/digest-2026-W45.json -o digests/2026-W45.html
  render.py ... --template other.html    (default: template.html)

Without -o the page goes to stdout.
"""
import argparse
import json
import re
import sys
from datetime import date
from html import escape
from pathlib import Path

from common import CATEGORIES, ROOT, load_feeds


def format_day(iso: str) -> str:
    day = date.fromisoformat(iso)
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"


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

    stories = json.loads(Path(args.json_path).read_text())
    match = re.search(r"(\d{4})-W(\d{2})\.json$", args.json_path)
    week_label = f"Week {int(match.group(2))}, {match.group(1)}" if match else "Weekly digest"
    days = sorted(s["date"] for s in stories)
    date_range = f"{format_day(days[0])} – {format_day(days[-1])}" if days else ""

    regions = (render_region(r, [s for s in stories if s["region"] == r]) for r in load_feeds()
               if any(s["region"] == r for s in stories))
    page = ((ROOT / args.template).read_text()
            .replace("{{WEEK}}", escape(week_label))
            .replace("{{RANGE}}", escape(date_range))
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
