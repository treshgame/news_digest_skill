"""Paths, limits and file helpers shared by the digest scripts."""
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PERIOD_TXT = DATA / "period.txt"    # titles only, what the AI reads first
PERIOD_JSON = DATA / "period.json"  # id -> full item, what the scripts look up

CONFIG = ROOT / "config.yml"

CATEGORIES = ("politics", "finance", "tech")

MAX_EXPLANATION_CHARS = 180

# Settings in config.yml and their defaults. Story limits are per day of the period (a 7-day digest
# allows 7x as many); -1 means no limit.
DEFAULT_CONFIG = {
    "language": "English",
    "newsPerCategoriesInRegion": 6,
    "newsPerRegions": -1,
}


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def atomic_write(path: Path, text: str) -> None:
    """Write through a temp file, so a power cut never leaves a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def load_config() -> dict:
    """Return config.yml merged over DEFAULT_CONFIG. A missing file means all defaults."""
    import yaml  # imported here, so the fetcher runs without PyYAML

    config = dict(DEFAULT_CONFIG)
    if CONFIG.exists():
        try:
            loaded = yaml.safe_load(CONFIG.read_text()) or {}
        except yaml.YAMLError as exc:
            fail(f"config.yml is not valid YAML: {exc}")
        if not isinstance(loaded, dict):
            fail("config.yml must be a list of `key: value` lines")
        unknown = loaded.keys() - DEFAULT_CONFIG.keys()
        if unknown:
            fail(f"unknown settings in config.yml: {', '.join(sorted(map(str, unknown)))}; "
                 f"known: {', '.join(DEFAULT_CONFIG)}")
        config.update({key: value for key, value in loaded.items() if value is not None})

    if not isinstance(config["language"], str) or not config["language"].strip():
        fail("config.yml: language must be a language name, e.g. English")
    config["language"] = config["language"].strip()
    for key in ("newsPerCategoriesInRegion", "newsPerRegions"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or (value < 1 and value != -1):
            fail(f"config.yml: {key} must be a whole number of 1 or more, or -1 for no limit (got {value!r})")
    return config


def format_cap(cap: int | None) -> str:
    return "no limit" if cap is None else str(cap)


def load_feeds() -> dict[str, list[dict]]:
    """Return region -> feeds, in file order. Feed names must be unique."""
    config = tomllib.loads((ROOT / "feeds.toml").read_text())
    feeds = {region: section["feeds"] for region, section in config.items()}
    names = [feed["name"] for region_feeds in feeds.values() for feed in region_feeds]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        fail(f"duplicate feed names in feeds.toml: {', '.join(sorted(duplicates))}")
    return feeds


# ---------- periods ----------
# A period is the run of UTC days a digest covers. Its id is "2026-11-14" for one day,
# "2026-11-08_2026-11-14" for several; a second digest of the same days gets "-2", "-3"...
# Old weekly ids ("2026-W45") are still understood.

def period_id(first: date, last: date) -> str:
    return first.isoformat() if first == last else f"{first.isoformat()}_{last.isoformat()}"


def period_bounds(period: str) -> tuple[date, date]:
    """Return (first day, last day) of a period id; raise ValueError if it is not one."""
    week = re.fullmatch(r"(\d{4})-W(\d{2})", period)
    if week:
        year, number = int(week.group(1)), int(week.group(2))
        return date.fromisocalendar(year, number, 1), date.fromisocalendar(year, number, 7)
    days = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:_(\d{4}-\d{2}-\d{2}))?(?:-\d+)?", period)
    if not days:
        raise ValueError(f"not a period: {period}")
    first = date.fromisoformat(days.group(1))
    last = date.fromisoformat(days.group(2)) if days.group(2) else first
    if last < first:
        raise ValueError(f"period ends before it starts: {period}")
    return first, last


def digest_path(period: str) -> Path:
    return DATA / f"digest-{period}.json"


def load_period() -> dict:
    """Return the exported period: {"period", "days", "language", "cap", "region_cap", "items": {id: item},
    "covered": [id]}. A cap of None means no limit."""
    if not PERIOD_JSON.exists():
        fail("no exported period; run `python3 fetch.py export` first")
    return json.loads(PERIOD_JSON.read_text())
