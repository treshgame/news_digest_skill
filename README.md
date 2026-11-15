# newsdigest

An agent skill that turns a week of RSS headlines into a one-page, printable newspaper. It works with any AI agent that can run shell commands: the agent only reads text and picks stories against your interests, so a small, cheap model is enough.

Reading the news every day eats time. This skill lets a script collect headlines in the background, lets an AI pick the few stories that matter to you, and gives you **one digest per week**: regions as pages, and politics, finance and tech as columns.

## How it works

```
fetch.py fetch      RSS feeds ──► local store (incremental, several times a day)
fetch.py export     store ──► data/week.txt (titles only, cheap to read)
        │
        ▼  the AI reads interests.md + week.txt and shortlists stories
fetch.py show       descriptions of the shortlisted stories
read_article.py     (rare) full text of an article, capped
addnews.py          the AI saves its picks: id | category | explanation
        │
        ▼
render.py           digest JSON + template.html ──► one HTML file
fetch.py clean      drop the processed week from the store
```

Design rules that keep it cheap and safe:

- **Scripts do the mechanical work.** The AI never searches the web, never writes JSON or HTML, and refers to stories by a 6-character id.
- **Few tokens.** The AI sees titles only at first (at most 3 items per feed per day), then descriptions for about 8 candidates per category in each region. Weak, cheap models work fine.
- **Feed text is untrusted.** `SKILL.md` tells the model to ignore any instructions found inside headlines or articles.
- **Output:** up to 6 stories per category in each region, explanations of at most 180 characters. Print it on A4: each region starts a new page (a full region may take more than one).

## Requirements

- Python 3.11+ (uses `tomllib`)
- `pip install feedparser`
- Optional: `pip install trafilatura` for better article text in `read_article.py` (a simple built-in extractor is used otherwise)
- Any AI agent that can read files and run shell commands

## Setup

1. Clone the repo anywhere, for example `~/projects/newsdigest`.
2. Install the dependency: `pip install feedparser`.
3. Make your agent see the skill: put or link the folder where your agent loads skills from, or point the agent at `SKILL.md`. For example:
   ```
   ln -s ~/projects/newsdigest ~/.claude/skills/newsdigest
   ```
4. Digests are written to `digests/<week>.html` inside the project folder. To save them elsewhere (a notes vault, a synced folder), change the `-o` path in the render step of `SKILL.md`.
5. Create your interests file: `cp interests.example.md interests.md`, then edit it (see *Change your interests* below). `interests.md` is ignored by git, so your preferences stay private.
6. Test the fetcher: `python3 fetch.py fetch -v` prints one line per feed.
7. Ask your agent: *"make the weekly news digest"*, or have it follow `SKILL.md`.

Run the skill once a week, on Sunday or later. `export` picks the right week by itself: the current week on Sunday, otherwise the last finished one.

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

- **RSS or Atom with publication dates.** Items without dates cannot be placed in a week, so they are useless here. (This is why Nikkei was dropped.)
- **Descriptions in the feed.** The AI explains a story from the feed's summary. Feeds with an empty or truncated description produce weaker results.
- **English.** The explanations are written in English from the source text.
- **Reputable, regularly updated, one topic or region per feed.** Section feeds (`/politics`, `/business`) are better than one giant "all news" feed, because the cap is per feed.
- **Several outlets per region.** The AI prefers stories covered by more than one source, which filters noise.
- Check a feed before adding it: `python3 fetch.py fetch -v` shows how many items each feed returned and any errors.

## Fetch several times a day

RSS feeds only keep the latest items. A busy feed may hold just 5–10 hours of news, so fetching once a week loses almost everything. The fetcher is **incremental** and keeps per-feed state, so it is safe and cheap to run often.

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

Everything lives in `data/` (ignored by git): fetched items per feed, `week.txt` / `week.json` for the AI, and one `digest-<week>.json` per finished digest. Delete the folder to start fresh.

## Commands

| Command | What it does |
|---|---|
| `python3 fetch.py fetch [-v]` | Download new items from all feeds |
| `python3 fetch.py export [--week W] [--cap N]` | Write `data/week.txt` and `week.json` |
| `python3 fetch.py show ID...` | Print descriptions for the given ids |
| `python3 fetch.py clean --week W` | Remove that week and older from the store |
| `python3 addnews.py` | Save picks from stdin: `id\|category\|title\|explanation` |
| `python3 addnews.py --stats` | Show counts per region and category |
| `python3 render.py data/digest-W.json -o out.html` | Render the digest (`--template` for another design) |
| `python3 read_article.py ID` | Fetch article text (max 10 per run) |

## Customising the look

`template.html` is a plain HTML/CSS file with three placeholders: `{{WEEK}}`, `{{RANGE}}` and `{{BODY}}`. Edit it, or write your own and pass it with `render.py --template`. The default prints as one A4 page per region.

## Limits

- Regions come from the feed, not from the story's content, so an occasional story lands in an odd region.
- The per-feed daily cap (3 items) can hide a big story on a very busy day. Raise it with `export --cap N` at the cost of more tokens.
