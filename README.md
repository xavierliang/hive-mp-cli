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

## 一句话安装（推荐）

复制下面这段给你的 AI Agent（Claude Code / Cursor / OpenClaw / Codex 等）：

```
帮我安装 hive-mp-cli：https://resopod.ai/install/hive-mp-cli.md
```

国内学员用这条（自动走清华源 + npmmirror 镜像）：

```
帮我安装 hive-mp-cli：https://www.resopod.cn/install/hive-mp-cli.md
```

Agent 会读 marketplace 上的指南把所有依赖装好。装完一次扫码就能用。
已经装过想升级？把 `install` 换成 `install/hive-mp-cli-update.md` 即可。

## 备用：从 GitHub 直装（开发者 / Marketplace 不可达）

```bash
# 从 Release 装最新版
pipx install https://github.com/<org>/hive-mp-cli/releases/latest/download/hive_mp_cli-py3-none-any.whl

# 从 main 分支装（本地需要 git）
pipx install git+https://github.com/<org>/hive-mp-cli

# 然后装 Chromium
pipx run --spec hive-mp-cli playwright install chromium
hive-mp doctor
```

国内用户走 GitHub 较慢，**优先用上面的 marketplace 路径**。

## Features

- `hive-mp login` — QR login (scan with WeChat). Pure HTTP, no browser launch
- `hive-mp account add/list/remove/info` — manage subscribed public accounts
- `hive-mp sync [name] [--mode api|web]` — pull article list + body
  - **web mode** (default): browser fetches article body, more robust against
    WeChat's risk-control screen
  - **api mode**: pure HTTP, faster, but article body may be blocked
  - `--repair`: skip the list pull, only retry articles whose body never made
    it (`has_content=0`); safe to run even after the login token has expired
- `hive-mp article list/read/url/search` — query archive
- `hive-mp doctor` — runtime self-check (chromium / token / accounts / sync health / disk)
- All commands accept `--json` for agent consumption
- Standard exit codes: 0 ok / 1 user error / 2 network error / 3 login expired

## Install (开发者 / 从源码)

End-users 用上面的"一句话安装"。这一节是给本地开发用的：

```bash
git clone <this-repo>
cd hive-mp-cli
uv sync
uv run playwright install chromium    # required for `sync` (article body)
uv run hive-mp doctor                 # 自检
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
├── filter_rules.yaml                # optional HTML noise filter (see below)
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
| `has_content` | `1` if the body was fetched and a markdown file written, else `0` |
| `fetch_attempts` | retry counter; capped at 3 — past that the URL is treated as dead |
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
hive-mp sync <name> --repair           # only retry articles whose body never landed
```

The browser launches **once per `sync` invocation** and is reused across all
articles — this is the major change vs the upstream pattern, which started a
fresh browser per article (~2s × N overhead).

## Repair partial fetches

A regular `sync` skips any URL it has seen — by `has_content`, not just by
existence. The first time the body fetch fails (anti-crawler block, transient
network error, partial DOM render), the row is written with `has_content=0`
and `fetch_attempts=1`. Run `hive-mp sync <name> --repair` to refetch only
those rows; after `MAX_FETCH_ATTEMPTS=3` tries it gives up and the article is
counted as `skipped_dead`. `--repair` does **not** call the WeChat API, so it
keeps working after your login token has expired:

```bash
hive-mp sync <name> --repair --json
# → {"<name>": {"new":0, "existing":0, "repaired":7, "failed":1, "skipped_dead":2, "errors":[]}}
```

## Content filter rules

WeChat articles often carry guide-to-follow / share / reward sections that
clutter the markdown output. Drop a YAML file at
`~/.hive-mp/filter_rules.yaml` and the matching elements are stripped before
`html → markdown` conversion. The file is optional — if absent, no filtering
is applied:

```yaml
global:
  remove_selectors:
    - ".reward_area_personal_new"      # CSS selector via BeautifulSoup .select()
  remove_ids: []                       # match by element id
  remove_classes:
    - "rich_media_tool"                # match by class name
  remove_regex: []                     # re.sub(pat, '', html, flags=DOTALL)

accounts:
  "公众号A":                            # name from accounts.json
    remove_selectors:
      - "#js_profile_qrcode"
```

Account-scoped rules merge **with** (not replace) the global block. Edits to
the file take effect on the next `sync` run; no restart needed.

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
