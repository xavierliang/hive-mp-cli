# hive-mp-cli

Agent-friendly CLI for archiving WeChat Official Account (公众号) articles to local
markdown.

Built for AI agents that need to read recent articles from a list of subscribed
accounts: scan QR once, then run `hive-mp sync` to pull new articles into a
folder of markdown files, with metadata persisted to SQLite.

The crawler core is ported from
[we-mp-rss](https://github.com/rachelos/we-mp-rss) — the heavy FastAPI/Vue3
service was stripped, only the WeChat HTTP API client + Playwright body fetcher
+ anti-crawler scripts are kept.

## Features

- `hive-mp login` — QR login (scan with WeChat). Pure HTTP, no browser launch
- `hive-mp account add/list/remove/info` — manage subscribed public accounts
- `hive-mp sync [name] [--mode api|web]` — pull article list + body
  - **web mode** (default): browser fetches article body, more robust against
    WeChat's risk-control screen
  - **api mode**: pure HTTP, faster, but article body may be blocked
- `hive-mp article list/read/url/search` — query archive
- All commands accept `--json` for agent consumption
- Standard exit codes: 0 ok / 1 user error / 2 network error / 3 login expired

## Install

```bash
git clone <this-repo>
cd hive-mp-cli
uv sync
uv run playwright install chromium    # required for `sync` (article body)
```

Both `hive-mp` and `hive-mp-cli` binaries are registered.

## Quick start

```bash
hive-mp login                              # scan QR with WeChat (terminal ASCII + PNG)
hive-mp status                             # see token expiry
hive-mp account add "阮一峰的网络日志"
hive-mp sync "阮一峰的网络日志" --pages 1
ls ~/.hive-mp/articles/阮一峰的网络日志/    # → markdown files
hive-mp article list "阮一峰的网络日志" --json
```

## Data layout

```
~/.hive-mp/                          (override with HIVE_MP_HOME=...)
├── config.json
├── accounts.json                    # subscribed accounts (hand-editable)
├── token.json                       # cookie + token (chmod 600)
├── articles.db                      # SQLite: articles + sync_log
├── articles/<account>/              # markdown output
│   └── 2026-05-04--<title-slug>.md
└── logs/hive-mp-YYYY-MM-DD.log
```

SQLite schema (`articles` table):

| column | meaning |
|--------|---------|
| `id` | sha256(url) |
| `biz_id` / `faker_id` | WeChat account identifier |
| `url` | original `mp.weixin.qq.com/s/...` URL |
| `local_path` | relative to `~/.hive-mp/articles/` |
| `fetch_status` | `success` / `partial` / `blocked` / `deleted` / `metadata-only` |
| `publish_time` | unix timestamp |

## Architecture

```
src/hive_mp_cli/
├── cli.py                          # Typer entry
├── config.py                       # PATHS singleton, HIVE_MP_HOME override
├── log.py                          # standard logging + Rich + daily file rotation
├── auth/
│   ├── login.py                    # QR flow orchestration (sync polling loop)
│   ├── qrcode.py                   # PNG → terminal block-char render
│   └── token.py                    # ~/.hive-mp/token.json persistence
├── wechat/
│   ├── api.py                      # WeChatAPI client (login + search + list)
│   ├── article.py                  # ArticleFetcher (shared Playwright session)
│   ├── browser.py                  # Playwright wrapper
│   ├── anti_crawler.py             # UA pool + Playwright context options
│   ├── anti_crawler_*.js           # 895 lines of anti-detection JS (1:1 copy)
│   ├── parser.py                   # HTML clean → markdownify
│   └── gather/                     # api_mode + web_mode list iterators
├── storage/
│   ├── accounts.py                 # accounts.json CRUD
│   ├── db.py                       # SQLite schema + ops (WAL mode)
│   └── files.py                    # markdown file naming + dedup
└── commands/
    ├── login.py / status.py
    ├── account.py / sync.py / article.py
```

## Anti-crawler

The upstream's anti-detection setup is ported **1:1**:

- **HTTP path** (search, list articles): random UA from a 13-entry pool +
  random sleep (0–10s before pages, 1–3s before article, 3–10s after) +
  detection of `ret=200013` (frequency control) → halts that account
- **Browser path** (article body in web mode): Playwright Chromium + 895 lines
  of injected JS that hide WebDriver, fake `window.chrome`, mock plugins/WebGL/
  Canvas/AudioContext/font fingerprints, strip Selenium/Puppeteer leak
  variables. Files: `wechat/anti_crawler_{base,advanced,behavior}.js`.

Sleep budgets are intentionally slow — the WeChat 公众号管理后台 limits per
account+IP, and the sleeps mimic human pacing. For agent-driven use cases
(low frequency, single account) this is plenty conservative.

## Sync modes

```bash
hive-mp sync <name> --mode web         # default: list via HTTP, body via browser
hive-mp sync <name> --mode api         # all HTTP, faster, body may be blocked
hive-mp sync <name> --no-browser       # skip body, only catalog metadata
```

The browser launches **once per `sync` invocation** and is reused across all
articles — this is the major change vs the upstream pattern, which started a
fresh browser per article (~2s × N overhead).

## Development

```bash
uv sync --dev
uv run pytest                          # 33 tests (no network needed)
uv run hive-mp --help
```

Tests cover: token round-trip, accounts CRUD, SQLite schema + dedup, file
naming, HTML→markdown parsing, anti-crawler script bundling. The full
sync/login paths require interactive WeChat scan + the live API; not unit-
tested but designed to be debuggable through `~/.hive-mp/logs/`.

## Known limitations

- **Token expiry is short** (~2 hours typical): re-run `hive-mp login`
- **Frequency control 200013**: a triggered account aborts that sync; retry
  later
- **Image hosting**: markdown keeps original `mmbiz.qpic.cn` URLs, no local
  image archive (could add `--download-images` later)
- **No FTS**: `article search` is `LIKE`-based; for fuzzy search, agents
  should use `grep`/`Glob` over `~/.hive-mp/articles/`

## Background

This rewrite is documented at:
- `/Users/xavier/.claude/plans/review-fork-linear-wirth.md` — original
  inventory of the we-mp-rss fork, what to keep / strip
- `/Users/xavier/.claude/plans/graceful-crunching-brook.md` — execution plan
  for this CLI

## License

Same as upstream we-mp-rss (MIT).
