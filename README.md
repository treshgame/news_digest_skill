# newsdigest

An agent skill that turns RSS headlines into a one-page, printable newspaper, as often as you like: daily, every few days or weekly. It works with any AI agent that can run shell commands: the agent only reads text and picks stories against your interests, so a small, cheap model is enough.

Reading the news all day eats time. This skill lets a script collect headlines in the background, lets an AI pick the few stories that matter to you, and gives you **one digest with everything fetched since the last one**: regions as pages, and categories as columns.

## How it works

```
fetch.py fetch      RSS feeds ──► local store (incremental, several times a day)
fetch.py export     store ──► data/period.txt (titles only, cheap to read)
        │
        ▼  the AI reads interests.md + period.txt and shortlists stories
fetch.py show       descriptions of the shortlisted stories
read_article.py     (rare) full text of an article, capped
addnews.py          the AI saves its picks: id | category | explanation
        │
        ▼
render.py           digest JSON + template.html ──► one HTML file
fetch.py clean      mark the digested items, so the next digest starts after them
```

Design rules that keep it cheap and safe:

- **Scripts do the mechanical work.** The AI never searches the web, never writes JSON or HTML, and refers to stories by a 6-character id.
- **Few tokens.** The AI sees titles only at first (at most 3 items per feed per day), then descriptions for about 1.5× the story cap per category in each region. Weak, cheap models work fine.
- **Feed text is untrusted.** `SKILL.md` tells the model to ignore any instructions found inside headlines or articles.
- **Output:** by default up to 6 stories per category in each region **per day** of the period (see *Settings*), explanations of at most 180 characters. Print it on A4: each region starts a new page (a full region may take more than one).

## Requirements

- Python 3.11+ (uses `tomllib`)
- `pip install feedparser pyyaml` (the background fetcher needs only `feedparser`)
- Optional: `pip install trafilatura` for better article text in `read_article.py` (a simple built-in extractor is used otherwise)
- Any AI agent that can read files and run shell commands

## Setup

1. Clone the repo anywhere, for example `~/projects/newsdigest`.
2. Install the dependencies: `pip install feedparser pyyaml`.
3. Make your agent see the skill: put or link the folder where your agent loads skills from, or point the agent at `SKILL.md`. For example:
   ```
   ln -s ~/projects/newsdigest ~/.claude/skills/newsdigest
   ```
4. Digests are written to `digests/<period>.html` inside the project folder (e.g. `digests/2026-11-14.html` for one day, `digests/2026-11-08_2026-11-14.html` for a week; a second digest of the same days gets a `-2` suffix). To save them elsewhere (a notes vault, a synced folder), change the `-o` path in the render step of `SKILL.md`.
5. Create your interests file: `cp interests.example.md interests.md`, then edit it (see *Change your interests* below). `interests.md` is ignored by git, so your preferences stay private.
   Optionally adjust `config.yml`: digest language and story limits (see *Settings*).
6. Test the fetcher: `python3 fetch.py fetch -v` prints one line per feed.
7. Ask your agent: *"make the news digest"*, or have it follow `SKILL.md`. Arguments (e.g. `/newsdigest --days 3 --today` in Claude Code, or in words like *"news for the last 3 days"*):
   - none: everything fetched up to this moment that is not in a digest yet (see below).
   - `--days N`: only the last N whole days, up to yesterday.
   - `--days N --today`: the last N days up to and including today (`--days 1 --today` is today only).
   - `--keep`: keep the digested news in the store instead of deleting them; they are still marked as digested, so the next run without arguments skips them.

## How often to run it

As often as suits you. Without arguments, a digest takes **everything fetched up to that moment that is not in a digest yet**, today included. After each digest, `fetch.py clean` marks its news as digested, so the next one starts where this one stopped: nothing is skipped and nothing appears twice, whether you run it every evening, twice a week or after a month away.

A long gap makes a long digest, on purpose. The AI's job is to keep out what doesn't matter to you (see *Change your interests*), not to squeeze the period into a fixed size.

The limits grow with the period: by default up to **6 stories per category, per region, per day** the digest covers (`newsPerCategoriesInRegion` in `config.yml`):

| The digest covers | Cap per category in each region |
|---|---|
| 1 day | 6 |
| 2 days | 12 |
| 4 days | 24 |
| 7 days | 42 |

The caps are ceilings, not targets: the AI only adds stories that are worth it.

To look at specific days instead, use `--days N` (the last N whole days, up to yesterday) or `--days N --today` (up to now). These take every stored item of those days, digested or not.

The very first digest starts at the oldest stored item: the first fetch looks about a week back (`FIRST_RUN_DAYS` in `fetch.py`).

## Settings

`config.yml` in the project folder holds the settings. Delete a line, or the whole file, to use the defaults.

```yaml
language: English               # language of titles and explanations
newsPerCategoriesInRegion: 6    # most stories per category in each region, per day
newsPerRegions: -1              # most stories per region in total, per day
```

| Setting | Default | Meaning |
|---|---|---|
| `language` | `English` | The digest's language. Stories from sources in another language are translated by the AI. |
| `newsPerCategoriesInRegion` | `6` | Most stories per category (politics, finance, tech) in each region, **per day** of the period. `-1`: no limit, the AI alone decides what is worth including. |
| `newsPerRegions` | `-1` | Most stories in each region across all categories, **per day** of the period. `-1`: no limit, only the per-category limit applies. |

Limits are multiplied by the number of days the digest covers, so a weekly digest gets 7× the daily limit. `addnews.py` enforces them, so the AI cannot exceed them. Invalid values stop `fetch.py export` with an error that names the setting.

## Change your interests

Your personal file is `interests.md`. Create it by copying the template, `cp interests.example.md interests.md`; it is not tracked by git. Edit it any time. It is plain text that the AI reads before choosing stories. Keep it short, in three levels:

```
High priority: AI and open source, cybersecurity incidents, elections, sanctions.
Medium: energy, China-US relations.
Ignore: sports, celebrities, lifestyle, opinion pieces.
```

- **High** topics are picked first and get more space.
- **Medium** topics fill the gaps.
- **Ignore** topics are skipped even if they are big news.
- Name concrete topics ("interest rates", "Central Asia") rather than vague ones ("important things"). Specific words are what a small model can match against headlines.

## Change your sources

Sources live in `feeds.toml`. Each region is a table with a list of feeds:

```toml
[Europe]
feeds = [
  { name = "euronews", url = "https://www.euronews.com/rss?format=xml" },
  { name = "guardian-biz", url = "https://www.theguardian.com/business/europe-business/rss", cat = "finance" },
]
```

- **Region** (`[Europe]`): the section title and the page in the digest. Rename, add or remove regions freely. Order in the file is the order in the digest.
- **`name`**: a short label, **unique across the whole file**. The AI sees it next to every headline, and the per-feed cap uses it. Duplicates are rejected with an error.
- **`url`**: the RSS or Atom address.
- **`cat`** (optional): `politics`, `finance` or `tech`. Only a hint for the AI, which makes the final call. Use it for specialised feeds.
- A story belongs to the region of the feed it came from. Put a feed under the region you want its stories to appear in.

If you add a region, check that categories still make sense: the digest always uses the same three columns, `politics`, `finance` and `tech` (set in `common.py`).

### What makes a good source

- **RSS or Atom with publication dates.** Items without dates cannot be placed on a day, so they are useless here. (This is why Nikkei was dropped.)
- **Descriptions in the feed.** The AI explains a story from the feed's summary. Feeds with an empty or truncated description produce weaker results.
- **Language.** Any language works: the AI translates stories into the `language` set in `config.yml`. Sources already in that language give the most faithful results.
- **Reputable, regularly updated, one topic or region per feed.** Section feeds (`/politics`, `/business`) are better than one giant "all news" feed, because the cap is per feed.
- **Several outlets per region.** The AI prefers stories covered by more than one source, which filters noise.
- Check a feed before adding it: `python3 fetch.py fetch -v` shows how many items each feed returned and any errors.

## Fetch several times a day

RSS feeds only keep the latest items. A busy feed may hold just 5–10 hours of news, so fetching only when you make a digest loses almost everything. The fetcher is **incremental** and keeps per-feed state, so it is safe and cheap to run often.

**Recommendation: every 4 hours, plus shortly after boot** (if the computer is off at night, the boot run catches up on whatever the feeds still hold).

### Linux (systemd user timer)

The `systemd/` folder has a ready service and timer. The service runs `~/.claude/skills/newsdigest/fetch.py` (the example link from the setup step). If your skill folder is elsewhere, change the `ExecStart` path in `newsdigest-fetch.service`.

```
mkdir -p ~/.config/systemd/user
cp systemd/newsdigest-fetch.service systemd/newsdigest-fetch.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now newsdigest-fetch.timer
```

Check that it works:

```
systemctl --user list-timers newsdigest-fetch.timer
systemctl --user start newsdigest-fetch.service     # run once now
journalctl --user -u newsdigest-fetch.service -n 20
```

### Any system (cron)

```
crontab -e
# every 4 hours
0 */4 * * * /usr/bin/python3 /path/to/newsdigest/fetch.py fetch
```

On macOS use `launchd`, on Windows Task Scheduler, with the same command: `python3 fetch.py fetch`.

### What gets stored

Everything lives in `data/` (ignored by git): fetched items (with a `done` mark once digested), `period.txt` / `period.json` for the AI, and one `digest-<period>.json` per finished digest. Delete the folder to start fresh.

## Commands

| Command | What it does |
|---|---|
| `python3 fetch.py fetch [-v]` | Download new items from all feeds |
| `python3 fetch.py export [--days N [--today]] [--cap N]` | Write `data/period.txt` and `period.json`. Default: every item not yet digested, up to now |
| `python3 fetch.py show ID...` | Print descriptions for the given ids |
| `python3 fetch.py clean [--keep]` | Mark the exported items as digested and delete them (`--keep`: only mark) |
| `python3 addnews.py` | Save picks from stdin: `id\|category\|title\|explanation` |
| `python3 addnews.py --stats` | Show counts per region and category |
| `python3 render.py data/digest-P.json -o out.html` | Render the digest (`--template` for another design) |
| `python3 read_article.py ID` | Fetch article text (max 10 per run) |

## Customising the look

`template.html` is a plain HTML/CSS file with two placeholders: `{{PERIOD}}` (e.g. *Sun 8 Nov – Sat 14 Nov 2026 · 7 days*) and `{{BODY}}`. Edit it, or write your own and pass it with `render.py --template`. The default prints as one A4 page per region.

## Limits

- Regions come from the feed, not from the story's content, so an occasional story lands in an odd region.
- The per-feed daily cap (3 items) can hide a big story on a very busy day. Raise it with `export --cap N` at the cost of more tokens.
- Days are UTC days, so a story published late in the evening in the Americas may count as the next day.
- Digested items are deleted only once they are older than the fetcher's 6-hour re-read window, so very recent ones stay (marked) until a later `clean`. Otherwise the next fetch would add them again.
