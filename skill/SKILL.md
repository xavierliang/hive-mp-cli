---
name: hive-mp-cli
description: >
  微信公众号文章归档工具。订阅公众号、扫码登录、把文章拉成本地 markdown。
  数据落 ~/.hive-mp/，所有命令支持 --json。

  【路由方式】SKILL.md 包含路由表和常用命令，细节场景查阅 references/*.md。
  分类：sync（拉文章 / 修复）/ filter（HTML 噪音过滤）/ troubleshooting（反爬、token 过期）。
triggers:
  - 公众号: 公众号/微信文章/mp.weixin/wechat/订阅号
  - 同步: 同步/归档/拉取/抓取/sync
  - 查询: 文章/article/读文章/搜文章
metadata:
  homepage: https://github.com/xavierliang/hive-mp-cli
---

# hive-mp-cli — 路由器

WeChat 公众号文章本地归档 CLI。数据全部在 `~/.hive-mp/`，**不要在用户的当前工作目录创建文件**。

## 路由表

| 用户意图 | 命令 | 详细 |
|---------|------|------|
| 登录 / 重新登录 | `hive-mp login` | — |
| 查看登录状态 | `hive-mp status --json` | 默认远端验证；只看本地用 `--local-only` |
| 加公众号 | `hive-mp account add "<名字>"` | — |
| 列公众号 | `hive-mp account list --json` | — |
| 删公众号 | `hive-mp account remove "<名字>"` | — |
| 同步文章 | `hive-mp sync "<名字>" --pages 1` | [references/sync.md](references/sync.md) |
| 修复未完成 | `hive-mp sync "<名字>" --repair` | [references/sync.md](references/sync.md) |
| 查文章列表 | `hive-mp article list "<名字>" --json` | — |
| 读单篇文章 | `hive-mp article read <id-or-url>` | — |
| 搜文章 | `hive-mp article search "<关键词>" --json` | — |
| 自检 | `hive-mp doctor --json` | — |
| HTML 噪音过滤 | 编辑 `~/.hive-mp/filter_rules.yaml` | [references/filter.md](references/filter.md) |

## 数据位置

```
~/.hive-mp/
├── config.json
├── accounts.json          # 订阅列表（可手编）
├── token.json             # 登录态（chmod 600）
├── articles.db            # SQLite，文章元数据
├── articles/<account>/    # markdown 文件
│   └── 2026-05-04--<title-slug>.md
├── filter_rules.yaml      # 可选：HTML 过滤规则
└── logs/hive-mp-YYYY-MM-DD.log
```

**所有持久产物在 `~/.hive-mp/`**。临时输出用 `/tmp/`。**禁止**在用户的项目目录（agent workspace）落文件。

## Exit Code 约定

所有命令统一：

- `0` — 成功
- `1` — 用户错误（参数错、账户不存在、accounts.json 损坏）
- `2` — 网络错误 / 反爬触发（200013 frequency control）
- `3` — Token 过期 → 需要重新 `hive-mp login`

JSON 模式下错误结构是 `{"ok": false, "error": "<code>", "message": "...", ...}`。

## JSON 输出

**几乎所有命令**都支持 `--json`，给你这种 Agent 用。优先用 JSON 模式，stderr 上的彩色输出忽略即可。

例：

```bash
hive-mp doctor --json
# {"ok": true, "summary": "ok", "checks": [...]}

hive-mp account list --json
# [{"biz_id": "MzA5...", "name": "阮一峰的网络日志", "last_synced": 1715000000}, ...]
```

### 特例：sync 不要加 `--json`

`hive-mp sync` 默认逐行打印每篇文章的进度到 stdout（`✓ 标题` / `✗ 标题`），自然语言、agent 直接读懂。加 `--json` 会把整个过程憋到结束才输出，反而失去进度感、容易让你误以为命令卡死。详见 [references/sync.md](references/sync.md)。

## 反爬注意

- WeChat 对单 IP+账户做频率控制，**不要循环高频跑 sync**
- 触发 `200013` 后 CLI 会本地写入 cooldown，强行重试会延长封锁
- 反爬触发时，让用户**等几个小时**再试。期间可以用 `--repair` 补未完成文章（不调用 WeChat API）

## 详细文档

- [references/sync.md](references/sync.md) — sync 模式（api / web）+ --repair + --pages 用法
- [references/filter.md](references/filter.md) — filter_rules.yaml 配置（YAML 选择器去除推广段落）
- [references/troubleshooting.md](references/troubleshooting.md) — 常见错误 + Token 过期 + 反爬恢复
