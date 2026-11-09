"""Paths, limits and file helpers shared by the digest scripts."""
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WEEK_TXT = DATA / "week.txt"    # titles only, what the AI reads first
WEEK_JSON = DATA / "week.json"  # id -> full item, what the scripts look up

CATEGORIES = ("politics", "finance", "tech")

# These limits keep the digest on one A4 page. Tested with render.py + a browser.
MAX_STORIES_PER_REGION = 6
MAX_EXPLANATION_CHARS = 180


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def atomic_write(path: Path, text: str) -> None:
    """Write through a temp file, so a power cut never leaves a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def load_feeds() -> dict[str, list[dict]]:
    """Return region -> feeds, in file order. Feed names must be unique."""
    config = tomllib.loads((ROOT / "feeds.toml").read_text())
    feeds = {region: section["feeds"] for region, section in config.items()}
    names = [feed["name"] for region_feeds in feeds.values() for feed in region_feeds]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        fail(f"duplicate feed names in feeds.toml: {', '.join(sorted(duplicates))}")
    return feeds


def load_week() -> dict:
    """Return the exported week: {"week": "2026-W45", "items": {id: item}}."""
    if not WEEK_JSON.exists():
        fail("no exported week; run `python3 fetch.py export` first")
    return json.loads(WEEK_JSON.read_text())


def digest_path(week: str) -> Path:
    return DATA / f"digest-{week}.json"
