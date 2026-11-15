#!/usr/bin/env python3
"""Incremental RSS fetcher for the news digest.

  fetch.py fetch [-v]                          fetch what is new since the last successful fetch of each feed
  fetch.py export [--days N [--today]]        write data/period.txt (titles, for the AI) and data/period.json
  fetch.py show ID [ID ...]                    print date and description for the shortlisted ids
  fetch.py clean [--keep]                      delete the exported items (--keep: only mark them as digested)

export without flags: every stored item not yet in a digest, up to this moment (today included).
export --days N: the last N whole UTC days up to yesterday; with --today, up to and including today.
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
from datetime import date, datetime, timedelta, timezone

import feedparser

from common import (DATA, MAX_STORIES_PER_CATEGORY_PER_DAY, PERIOD_JSON, PERIOD_TXT, atomic_write, digest_path,
                    fail, load_feeds, load_period, period_id)

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


def item_day(item: dict) -> date:
    return utc(item["ts"]).date()


def days_window(args) -> tuple[date, date]:
    """First and last day of --days N: up to yesterday, or up to today with --today."""
    last = datetime.now(timezone.utc).date() - timedelta(days=0 if args.today else 1)
    return last - timedelta(days=args.days - 1), last


def select_items(args, stored: list[dict]) -> list[dict]:
    """The items to export: the chosen days, or everything not yet in a digest."""
    if args.days:
        first, last = days_window(args)
        chosen = [i for i in stored if first <= item_day(i) <= last]
        if not chosen:
            fail(f"no items from {first} to {last}")
        return chosen
    chosen = [i for i in stored if not i.get("done")]
    if not chosen:
        fail("nothing new to digest: every stored item is already in a digest. Run `python3 fetch.py fetch` "
             "later, or pick days with --days N")
    return chosen


def unique_period_id(first: date, last: date) -> str:
    """Period id for these days; a second digest of the same days gets a -2, -3... suffix."""
    base = period_id(first, last)
    period, number = base, 1
    while digest_path(period).exists():
        number += 1
        period = f"{base}-{number}"
    return period


def load_items() -> dict[str, dict]:
    if not ITEMS.exists():
        return {}
    items = (json.loads(line) for line in ITEMS.read_text().splitlines() if line.strip())
    return {item["id"]: item for item in items}


def save_items(items: dict[str, dict]) -> None:
    atomic_write(ITEMS, "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items.values()))


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"feeds": {}}


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


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
    """Keep each feed's newest `cap` items of every day, so a busy feed can't crowd out the others."""
    seen = collections.Counter()
    kept = []
    for item in sorted(items, key=lambda i: -i["ts"]):
        key = (item["source"], iso_day(item["ts"]))
        seen[key] += 1
        if seen[key] <= cap:
            kept.append(item)
    return kept


def cmd_export(args) -> int:
    regions = list(load_feeds())
    stored = [i for i in load_items().values() if i["region"] in regions]
    in_period = select_items(args, stored)
    if args.days:  # the period is the days asked for, even if some of them are empty
        first, last = days_window(args)
    else:  # the days the not-yet-digested items span
        first, last = min(item_day(i) for i in in_period), max(item_day(i) for i in in_period)
    period, days = unique_period_id(first, last), (last - first).days + 1
    story_cap = MAX_STORIES_PER_CATEGORY_PER_DAY * days
    kept = cap_per_feed_per_day(in_period, args.cap)

    span = f"{days} day{'s' if days > 1 else ''}"
    lines = [f"# period {period} ({span}), up to {story_cap} stories per category in each region",
             "# id|source[/category hint]|title"]
    for region in regions:
        lines.append(f"## {region}")
        for item in (i for i in kept if i["region"] == region):
            source = item["source"] + (f"/{item['cat']}" if item.get("cat") else "")
            lines.append(f"{item['id']}|{source}|{field(item['title'])}")
    text = "\n".join(lines) + "\n"
    atomic_write(PERIOD_TXT, text)

    index = {i["id"]: {"region": i["region"], "date": iso_day(i["ts"]), "source": i["source"],
                       "title": i["title"], "desc": i["desc"], "link": i["link"]} for i in kept}
    # "covered" lists every item of the period, also those the per-feed cap left out, so `clean` retires them all.
    atomic_write(PERIOD_JSON, json.dumps({"period": period, "days": days, "cap": story_cap, "items": index,
                                          "covered": [i["id"] for i in in_period]}, ensure_ascii=False))
    (DATA / "articles_read.txt").unlink(missing_ok=True)
    print(f"exported {len(kept)} of {len(in_period)} items for period {period} ({span}): "
          f"~{len(text) // 4} tokens; cap {story_cap} stories per category in each region")
    return 0


def cmd_show(args) -> int:
    items = load_period()["items"]
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
    """Retire the exported items, so the next export without flags starts after them."""
    exported = load_period()
    period = exported["period"]
    if not digest_path(period).exists():
        fail(f"no digest for {period} yet; cleaning would lose the period's items")
    covered = set(exported.get("covered", exported["items"]))
    items = load_items()
    for item_id in covered & items.keys():
        items[item_id]["done"] = True
    if args.keep:
        result = f"marked {len(covered & items.keys())} items of {period} as digested and kept them"
    else:
        # A digested item still inside a feed's re-fetch window must stay, or the next fetch would add it again.
        last_fetches = [load_state()["feeds"].get(f["url"], 0) for fs in load_feeds().values() for f in fs]
        safe_before = min(last_fetches, default=0) - OVERLAP_SECONDS
        left = {k: v for k, v in items.items() if not (v.get("done") and v["ts"] < safe_before)}
        result = (f"digested {len(covered)} items of {period}; removed {len(items) - len(left)} digested items, "
                  f"{sum(1 for v in left.values() if v.get('done'))} recent ones stay until the next clean")
        items = left
    save_items(items)
    for path in (PERIOD_TXT, PERIOD_JSON, DATA / "articles_read.txt"):
        path.unlink(missing_ok=True)
    print(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="cmd", required=True)

    p = commands.add_parser("fetch")
    p.add_argument("-v", "--verbose", action="store_true", help="print one line per feed")
    p.set_defaults(fn=cmd_fetch)

    p = commands.add_parser("export")
    p.add_argument("--days", type=positive_int,
                   help="the last N whole days up to yesterday (default: everything not yet digested, up to now)")
    p.add_argument("--today", action="store_true", help="with --days: count up to and including today")
    p.add_argument("--cap", type=int, default=DEFAULT_CAP_PER_FEED_PER_DAY, help="max items per feed per day")
    p.set_defaults(fn=cmd_export)

    p = commands.add_parser("show")
    p.add_argument("ids", nargs="+")
    p.set_defaults(fn=cmd_show)

    p = commands.add_parser("clean")
    p.add_argument("--keep", action="store_true", help="keep the items, only mark them as digested")
    p.set_defaults(fn=cmd_clean)

    args = parser.parse_args()
    if getattr(args, "today", False) and not args.days:
        parser.error("--today goes with --days N; without --days the export already runs up to now")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
