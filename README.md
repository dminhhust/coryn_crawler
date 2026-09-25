# Coryn Club Crawler

A small, resumable Python crawler for Coryn Club's **public read-only JSON API**.

It collects:

- all items
- item stats (via detail lookups)
- all monsters
- bosses / mini-bosses
- monster drop relationships
- all maps
- map → monster relationships

The crawler uses Coryn's documented API instead of scraping HTML pages.

## API used

- `https://coryn.club/api/v1/items.php`
- `https://coryn.club/api/v1/monsters.php`
- `https://coryn.club/api/v1/maps.php`

The documented maximum page size is 100, so the crawler paginates with `limit` and `offset`.

## Project layout

```text
coryn-crawler/
├── .env.example
├── pyproject.toml
├── requirements.txt
├── README.md
├── src/
│   └── coryn_crawler/
│       ├── api.py
│       ├── cli.py
│       ├── config.py
│       ├── exporters.py
│       ├── http.py
│       ├── normalize.py
│       └── storage.py
└── tests/
    ├── test_api.py
    └── test_normalize.py
```

Runtime output:

```text
data/
├── raw/
│   ├── items.jsonl
│   ├── monsters.jsonl
│   ├── maps.jsonl
│   ├── items_details.jsonl
│   ├── monsters_details.jsonl
│   └── details/
│       ├── items/<id>.json
│       └── monsters/<id>.json
└── processed/
    ├── items.csv
    ├── item_stats.csv
    ├── monsters.csv
    ├── bosses.csv
    ├── monster_drops.csv
    ├── maps.csv
    └── map_monsters.csv
```

## 1. Setup

### PowerShell

```powershell
cd coryn-crawler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

### Linux/macOS

```bash
cd coryn-crawler
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## 2. Crawl only the paginated collections

Fastest / fewest requests:

```powershell
coryn-crawl crawl all
```

Or separately:

```powershell
coryn-crawl crawl items
coryn-crawl crawl monsters
coryn-crawl crawl maps
```

## 3. Complete crawl including item stats and monster drops

```powershell
coryn-crawl full
```

`full` does this:

1. paginate all items, monsters, and maps;
2. cache an ID detail response for each item;
3. cache an ID detail response for each monster;
4. export normalized CSV tables.

Because the site has thousands of records, this intentionally runs sequentially with a configurable delay rather than hammering the API.

If interrupted, run the exact command again. Existing detail files are reused.

## 4. Fetch details for only one resource

```powershell
coryn-crawl crawl items --details
coryn-crawl crawl monsters --details
```

Maps are lightweight; their collection response is normally enough for `maps.csv`.

## 5. Export CSVs again without re-crawling

```powershell
coryn-crawl export
```

If detailed files exist, they are preferred automatically.

To export only collection-level information:

```powershell
coryn-crawl export --no-prefer-details
```

## 6. Configuration

Edit `.env`:

```dotenv
CORYN_BASE_URL=https://coryn.club/api/v1
CORYN_PAGE_SIZE=100
CORYN_REQUEST_DELAY=0.30
CORYN_TIMEOUT=30
CORYN_MAX_RETRIES=5
CORYN_USER_AGENT=CorynResearchCrawler/0.1 (educational data collection; public API)
CORYN_OUTPUT_DIR=data
```

For a public community API, keep a non-zero delay. If you receive HTTP 429, the code backs off automatically.

## 7. Output tables

### `items.csv`

One row per item:

```text
item_id,name,type_id,type_label,sell,process,process_amount,badge,note
```

### `item_stats.csv`

One row per item/stat pair:

```text
item_id,item_name,effect_id,effect_name,amount,applies_to
```

### `monsters.csv`

One row per monster record/difficulty:

```text
monster_id,name,level,map_id,map_name,type_code,type_label,mode,hp,exp,element_id,element_label,...
```

### `bosses.csv`

Subset of monster rows where `type_label` contains `boss`. Do **not** deduplicate solely by boss name because different difficulty/mode records may exist.

### `monster_drops.csv`

Relationship table:

```text
monster_id,monster_name,monster_type,monster_level,monster_mode,map_id,map_name,item_id,item_name,item_type_id,item_type_label
```

### `maps.csv`

```text
map_id,name,monster_count
```

### `map_monsters.csv`

Relationship table reconstructed from each monster's map fields.

## 8. Run tests

```powershell
pip install pytest
pytest -q
```

The tests use a fake HTTP client, so they do not hit Coryn Club.

## Notes

- Uses only public read-only endpoints.
- No login/session scraping.
- No Selenium required.
- Pagination and details are resumable.
- Individual detail objects are cached as `data/raw/details/<resource>/<id>.json`.
- `--no-resume` disables reuse of crawler state/detail caches.
