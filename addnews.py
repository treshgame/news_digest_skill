#!/usr/bin/env python3
"""The only way for the AI to write digest data.

  addnews.py <<'EOF'                 add stories, one per line: id|category|title|explanation
  a3f9c1|finance||Fed held rates.    (empty title = keep the feed's title)
  EOF
  addnews.py --stats                 stories per region and category
  addnews.py --remove ID [ID ...]    take stories out

Region, date and link come from the id. Valid lines are saved even if others fail,
and an id already in the digest is skipped, so fixing and resending is always safe.
"""
import argparse
import collections
import json
import sys

from common import (CATEGORIES, MAX_EXPLANATION_CHARS, MAX_STORIES_PER_CATEGORY, atomic_write, digest_path,
                    fail, load_feeds, load_week)


def load_digest(week: str) -> list[dict]:
    path = digest_path(week)
    return json.loads(path.read_text()) if path.exists() else []


def save_digest(week: str, stories: list[dict]) -> None:
    atomic_write(digest_path(week), json.dumps(stories, indent=1, ensure_ascii=False))


def stats_line(stories: list[dict]) -> str:
    parts = []
    for region in load_feeds():
        count = collections.Counter(s["category"] for s in stories if s["region"] == region)
        detail = " ".join(f"{c[0]}{count[c]}" for c in CATEGORIES)  # p2 f1 t3
        parts.append(f"{region}={sum(count.values())} ({detail})")
    return f"{', '.join(parts)}; total={len(stories)}, max {MAX_STORIES_PER_CATEGORY} per category in a region"


def parse_line(line: str) -> tuple[str, str, str, str]:
    """Accept id|category|title|explanation and the id|category|explanation shorthand."""
    parts = [part.strip() for part in line.split("|", 3)]
    if len(parts) == 3:
        return parts[0], parts[1], "", parts[2]
    if len(parts) == 4:
        return parts[0], parts[1], parts[2], parts[3]
    raise ValueError("expected id|category|title|explanation")


def add_story(line: str, stories: list[dict], items: dict) -> str:
    """Append the line's story to stories. Return "added" or "skipped"; raise ValueError if invalid."""
    story_id, category, title, explanation = parse_line(line)
    if story_id not in items:
        raise ValueError(f"unknown id {story_id}")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(CATEGORIES)}")
    if len(explanation) > MAX_EXPLANATION_CHARS:
        raise ValueError(f"explanation is {len(explanation)} chars, max {MAX_EXPLANATION_CHARS}; shorten it")
    if any(s["id"] == story_id for s in stories):
        return "skipped"
    item = items[story_id]
    if sum(s["region"] == item["region"] and s["category"] == category for s in stories) >= MAX_STORIES_PER_CATEGORY:
        raise ValueError(f"{item['region']} already has {MAX_STORIES_PER_CATEGORY} {category} stories; "
                         "drop this one or use --remove first")
    stories.append({"id": story_id, "region": item["region"], "date": item["date"], "category": category,
                    "title": title or item["title"], "explanation": explanation, "link": item["link"]})
    return "added"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--remove", nargs="+", metavar="ID")
    args = parser.parse_args()

    week_data = load_week()
    week = week_data["week"]
    stories = load_digest(week)

    if args.stats:
        print(stats_line(stories))
        return 0

    if args.remove:
        missing = set(args.remove) - {s["id"] for s in stories}
        if missing:
            fail(f"not in digest: {' '.join(sorted(missing))}")
        stories = [s for s in stories if s["id"] not in args.remove]
        save_digest(week, stories)
        print(f"removed {len(args.remove)}; {stats_line(stories)}")
        return 0

    results, errors = collections.Counter(), 0
    for number, line in enumerate(sys.stdin, start=1):
        if not line.strip():
            continue
        try:
            results[add_story(line, stories, week_data["items"])] += 1
        except ValueError as exc:
            print(f"error line {number}: {exc}", file=sys.stderr)
            errors += 1
    save_digest(week, stories)
    print(f"added {results['added']}, skipped {results['skipped']}, errors {errors}; {stats_line(stories)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
