#!/usr/bin/env python3
"""Incremental RSS fetcher for the weekly news digest.

  fetch.py fetch [-v]              fetch what is new since the last successful fetch of each feed
  fetch.py export [--week W]       write data/week.txt (titles, for the AI) and data/week.json
  fetch.py show ID [ID ...]        print date and description for the shortlisted ids
  fetch.py clean [--week W]        delete that week's and older items, and the temp files

Default week: the current ISO week on Sunday, otherwise the last finished one.
Store: data/items.jsonl (all fetched items), data/state.json (last successful fetch per feed).
"""
import argparse
import calendar
import collections
import hashlib
import html
import json
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser

from common import DATA, WEEK_JSON, WEEK_TXT, atomic_write, digest_path, fail, load_feeds, load_week

ITEMS = DATA / "items.jsonl"
STATE = DATA / "state.json"

FIRST_RUN_DAYS = 7           # how far back to look the very first time
OVERLAP_SECONDS = 6 * 3600   # safety margin; duplicates are removed by id anyway
DESC_LEN = 200               # stored description length
NETWORK_TIMEOUT_SECONDS = 20
DEFAULT_CAP_PER_FEED_PER_DAY = 3

feedparser.USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) newsdigest/0.2"


# ---------- helpers ----------

def clean_text(text: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def short_id(link: str) -> str:
    return hashlib.sha1(link.encode()).hexdigest()[:6]


def norm_title(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def entry_timestamp(entry) -> int | None:
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return calendar.timegm(entry[key])
    return None


def utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def iso_day(ts: int) -> str:
    return utc(ts).strftime("%Y-%m-%d")


def format_week(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def default_week() -> str:
    """The week to digest: this one on Sunday, otherwise the last finished one."""
    now = datetime.now(timezone.utc)
    return format_week(now if now.isoweekday() == 7 else now - timedelta(days=7))


def load_items() -> dict[str, dict]:
    if not ITEMS.exists():
        return {}
    items = (json.loads(line) for line in ITEMS.read_text().splitlines() if line.strip())
    return {item["id"]: item for item in items}


def save_items(items: dict[str, dict]) -> None:
    atomic_write(ITEMS, "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items.values()))


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"feeds": {}}


def field(text: str) -> str:
    """Make text safe for a |-separated line."""
    return text.replace("|", "/")


# ---------- fetch ----------

def fetch_feed(feed: dict, region: str, items: dict, known_titles: set, last: int | None, now: int) -> tuple[int, int]:
    """Add the feed's new entries to items. Return (new, entries in the feed)."""
    parsed = feedparser.parse(feed["url"])
    if not parsed.entries:
        raise RuntimeError(f"no entries (status={parsed.get('status')}, error={parsed.get('bozo_exception')})")

    cutoff = last - OVERLAP_SECONDS if last else now - FIRST_RUN_DAYS * 86400
    new = 0
    for entry in parsed.entries:
        link, title = entry.get("link"), clean_text(entry.get("title", ""), 300)
        if not link or not title:
            continue
        ts = entry_timestamp(entry) or now  # undated entries count as "now"; the id dedupe protects us
        item_id, title_key = short_id(link), (region, norm_title(title))
        if ts < cutoff or item_id in items or title_key in known_titles:
            continue
        items[item_id] = {
            "id": item_id, "region": region, "source": feed["name"], "cat": feed.get("cat", ""), "ts": ts,
            "title": title, "desc": clean_text(entry.get("summary", ""), DESC_LEN), "link": link,
        }
        known_titles.add(title_key)
        new += 1
    return new, len(parsed.entries)


def cmd_fetch(args) -> int:
    socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)  # feedparser has no timeout of its own
    DATA.mkdir(exist_ok=True)
    items, state = load_items(), load_state()
    known_titles = {(i["region"], norm_title(i["title"])) for i in items.values()}
    now = int(time.time())
    total_new, failed = 0, 0

    for region, feeds in load_feeds().items():
        for feed in feeds:
            try:
                new, entries = fetch_feed(feed, region, items, known_titles, state["feeds"].get(feed["url"]), now)
            except Exception as exc:  # one dead feed must not stop the others
                print(f"WARN  {feed['name']}: {exc}", file=sys.stderr)
                failed += 1
                continue
            state["feeds"][feed["url"]] = now
            total_new += new
            if args.verbose:
                print(f"ok    {region:12} {feed['name']:16} +{new:<3} (feed has {entries})")

    save_items(items)
    atomic_write(STATE, json.dumps(state, indent=1))
    print(f"done: {total_new} new, {len(items)} stored, {failed} feed(s) failed")
    return 0


# ---------- export / show ----------

def cap_per_feed_per_day(items: list[dict], cap: int) -> list[dict]:
    """Keep each feed's newest `cap` items of every day, so a busy feed can't crowd out the week."""
    seen = collections.Counter()
    kept = []
    for item in sorted(items, key=lambda i: -i["ts"]):
        key = (item["source"], iso_day(item["ts"]))
        seen[key] += 1
        if seen[key] <= cap:
            kept.append(item)
    return kept


def cmd_export(args) -> int:
    week = args.week or default_week()
    regions = list(load_feeds())
    in_week = [i for i in load_items().values() if format_week(utc(i["ts"])) == week and i["region"] in regions]
    if not in_week:
        fail(f"no items for {week}")
    kept = cap_per_feed_per_day(in_week, args.cap)

    lines = [f"# week {week}", "# id|source[/category hint]|title"]
    for region in regions:
        lines.append(f"## {region}")
        for item in (i for i in kept if i["region"] == region):
            source = item["source"] + (f"/{item['cat']}" if item.get("cat") else "")
            lines.append(f"{item['id']}|{source}|{field(item['title'])}")
    text = "\n".join(lines) + "\n"
    atomic_write(WEEK_TXT, text)

    index = {i["id"]: {"region": i["region"], "date": iso_day(i["ts"]), "source": i["source"],
                       "title": i["title"], "desc": i["desc"], "link": i["link"]} for i in kept}
    atomic_write(WEEK_JSON, json.dumps({"week": week, "items": index}, ensure_ascii=False))
    (DATA / "articles_read.txt").unlink(missing_ok=True)
    print(f"exported {len(kept)} of {len(in_week)} items for {week}: ~{len(text) // 4} tokens")
    return 0


def cmd_show(args) -> int:
    items = load_week()["items"]
    unknown = [i for i in args.ids if i not in items]
    if unknown:
        print(f"unknown ids skipped: {' '.join(unknown)}", file=sys.stderr)
    print("# id|MM-DD|source|title|description")
    known = [items[i] | {"id": i} for i in dict.fromkeys(args.ids) if i in items]
    for region in load_feeds():
        chosen = [i for i in known if i["region"] == region]
        if chosen:
            print(f"## {region}")
        for i in chosen:
            print(f"{i['id']}|{i['date'][5:]}|{i['source']}|{field(i['title'])}|{field(i['desc'])}")
    return 0


# ---------- clean ----------

def cmd_clean(args) -> int:
    week = args.week or default_week()
    if not digest_path(week).exists():
        fail(f"no digest for {week} yet; cleaning would lose the week's items")
    items = load_items()
    keep = {k: v for k, v in items.items() if format_week(utc(v["ts"])) > week}  # YYYY-Www sorts by time
    save_items(keep)
    for path in (WEEK_TXT, WEEK_JSON, DATA / "articles_read.txt"):
        path.unlink(missing_ok=True)
    print(f"removed {len(items) - len(keep)} items up to {week}; {len(keep)} left")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="cmd", required=True)

    p = commands.add_parser("fetch")
    p.add_argument("-v", "--verbose", action="store_true", help="print one line per feed")
    p.set_defaults(fn=cmd_fetch)

    p = commands.add_parser("export")
    p.add_argument("--week", help="ISO week, e.g. 2026-W45")
    p.add_argument("--cap", type=int, default=DEFAULT_CAP_PER_FEED_PER_DAY, help="max items per feed per day")
    p.set_defaults(fn=cmd_export)

    p = commands.add_parser("show")
    p.add_argument("ids", nargs="+")
    p.set_defaults(fn=cmd_show)

    p = commands.add_parser("clean")
    p.add_argument("--week", help="ISO week, e.g. 2026-W45")
    p.set_defaults(fn=cmd_clean)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
