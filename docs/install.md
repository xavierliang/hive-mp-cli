# hive-mp-cli — 安装指南

## 给人看的

复制下面这段给你的 AI Agent（Claude Code / Cursor / OpenClaw / Codex 等）：

```
帮我安装 hive-mp-cli：{{SITE}}/install/hive-mp-cli.md
```

Agent 会读这份指南把所有依赖装好，**你不用做别的**。装完后扫一次微信二维码就能开始用。

> 安全说明：这个工具只会在 `~/.hive-mp/` 下读写文件，不会动你别的目录，也不会装 sudo 权限的东西（除非你明确同意）。

---

## 给 AI Agent 看的

### 你的目标

把 hive-mp-cli 装到用户机器上，让 `hive-mp doctor` 跑通（至少 chromium ✅、disk ✅），引导用户完成首次登录。

装完后用户的 Agent（也就是你）将能调用：

- `hive-mp login` — 扫码登录微信
- `hive-mp account add "<公众号名>"` — 订阅公众号
- `hive-mp sync "<名字>"` — 拉文章到本地 markdown
- `hive-mp article list/read/search` — 查询归档
- `hive-mp doctor` — 自检

### 边界（必须守）

- **不要 `sudo`**——除非用户明确授权。装包用 `--user` 或 `pipx`，不要碰系统 Python。
- **不要在 agent workspace（当前工作目录）创建文件**——会污染用户项目目录。所有持久文件落 `~/.hive-mp/`，临时文件用 `/tmp/`。
- **不要修改 `~/.hive-mp/` 之外的用户文件**。
- **不要禁用防火墙、安全设置**或其他系统保护。
- **需要提升权限时，先告诉用户**让他决定，不要替他做主。

### Step 1 — 探测网络环境

用户在中国大陆还是海外？这直接影响要不要用镜像源。判断依据（任选其一）：

- 系统 locale 是 `zh_CN` / 时区是 `Asia/Shanghai`
- 直接 ping 一下 `playwright.azureedge.net`，3 秒不通就当国内
- 不确定时直接问用户："你在中国大陆吗？这影响我要不要用国内镜像。"

后续命令里出现的 `<CN>` / `<GLOBAL>` 标记，按用户位置选其中一条跑。

### Step 2 — 装 pipx（如果没有）

先检查：`command -v pipx`。有就跳过。

没有：

```bash
# <GLOBAL>
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# <CN>
python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --user pipx
python3 -m pipx ensurepath
```

> macOS 用户如果遇到 `externally-managed-environment` 报错（PEP 668），这是 Homebrew Python 的保护机制，不是 hive-mp-cli 的问题。**解决办法**：用 `python3 -m pip install --user --break-system-packages pipx`，或者先 `brew install pipx`。

让用户重开一个 shell 或者 `source ~/.bashrc` / `source ~/.zshrc`，确保 `pipx` 在 PATH 里。

### Step 3 — 装 hive-mp-cli

```bash
pipx install {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl
```

国内用户 pipx 拉依赖时如果慢，可以提前给 pipx 配清华源：

```bash
# <CN> 一次性给 pipx 配上清华镜像，再装
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    pipx install {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl
```

验证：`hive-mp --version` 能跑出版本号就成功。

### Step 4 — 装 Chromium（Playwright 浏览器）

hive-mp 用 Playwright 抓文章正文，需要单独装 Chromium 二进制（~150MB）。**这一步对国内用户最关键**，默认 CDN 在国内基本不通。

```bash
# <GLOBAL>
pipx runpip hive-mp-cli install playwright >/dev/null   # 已经随包装好，这一步通常不需要，跳过
pipx run --spec hive-mp-cli playwright install chromium

# <CN>
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ \
    pipx run --spec hive-mp-cli playwright install chromium
```

如果 `npmmirror` 也慢，备用镜像：

```bash
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
    pipx run --spec hive-mp-cli playwright install chromium
```

> 这一步会下 150MB 左右，慢的话耐心等。装完 chromium 会落在 `~/Library/Caches/ms-playwright/`（macOS）或 `~/.cache/ms-playwright/`（Linux）。

### Step 5 — 自检

```bash
hive-mp doctor
```

应该看到至少 `chromium` 和 `disk` 是 ✅。`login` 和 `accounts` 这时候会是 ❌/⚠️ 是正常的（还没登录、还没订阅）。

加 `--json` 给你自己读：

```bash
hive-mp doctor --json
```

如果 `chromium` 是 ❌，回到 Step 4 重新装，或者参考 Troubleshooting。

### Step 6 — 引导用户首次登录

```bash
hive-mp login
```

会在终端打印一个 ASCII 二维码 + 保存一份 PNG 到 `~/.hive-mp/qrcode.png`。**提示用户用微信扫这个码**（不是 PC 微信，是手机微信）。扫完会自动写 `~/.hive-mp/token.json`。

> Token 大约 2 小时过期，过期后重跑 `hive-mp login` 即可。

### Step 7 — 引导用户订阅第一个公众号

```bash
hive-mp account add "<公众号名>"
```

举例："阮一峰的网络日志"。然后跑一次 sync 验证：

```bash
hive-mp sync "<公众号名>" --pages 1
```

跑通后 markdown 文章在 `~/.hive-mp/articles/<公众号名>/` 下。

### Step 8（可选）— 装 Skill

如果用户用 Claude Code / Cursor / OpenClaw 等支持 skill 的 Agent，把 skill 装上能让以后调用更顺滑（你自己以后接到"帮我同步 XX"这种请求时，会自动认得这些命令）：

```bash
# Claude Code
mkdir -p ~/.claude/skills/hive-mp-cli/
curl -L {{SITE}}/skills/hive-mp-cli.tar.gz | tar -xC ~/.claude/skills/hive-mp-cli/

# Cursor — 把路径换成 ~/.cursor/skills/ 或对应 skill 目录
# OpenClaw — ~/.openclaw/skills/hive-mp-cli/
```

如果用户不知道自己 Agent 的 skill 目录在哪，跳过这步不影响 CLI 使用。

---

## Quick Reference

| 命令 | 作用 |
|------|------|
| `pipx install {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl` | 装 CLI |
| `pipx run --spec hive-mp-cli playwright install chromium` | 装 Chromium |
| `hive-mp doctor` | 自检 |
| `hive-mp login` | 扫码登录 |
| `hive-mp account add "<名>"` | 订阅公众号 |
| `hive-mp sync "<名>"` | 拉文章 |
| `hive-mp sync "<名>" --repair` | 修复未完成的文章（不需要 token） |

国内用户全程加：

- pip: `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- playwright: `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/`

---

## Troubleshooting

### `externally-managed-environment` (PEP 668)
Homebrew Python 的保护。用 `pipx`（推荐）或加 `--break-system-packages` 参数。

### `playwright install chromium` 卡住 / 超时
99% 是网络问题。
- 国内用户：必须设 `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/`
- 海外用户：试翻墙 / 重试；也可能是 CDN 临时挂

### `hive-mp doctor` 显示 chromium ❌ 但 Step 4 跑过
- 检查 `~/Library/Caches/ms-playwright/` (macOS) / `~/.cache/ms-playwright/` (Linux) 是否有 `chromium-*` 目录
- 多个 Python 环境共存时，可能装到了别的 Playwright 上。用 `pipx run --spec hive-mp-cli playwright install chromium` 而不是 `playwright install chromium`，确保走 hive-mp-cli 的 Python 环境

### `hive-mp login` 扫码后没反应
- 用手机微信扫，不是 PC 微信
- 扫完要在手机上点"确认登录"
- 二维码 60 秒过期，过期重跑

### `hive-mp sync` 报 `login_expired` (exit 3)
Token 过期了（~2 小时）。`hive-mp login` 重扫一次即可。

### `hive-mp sync` 报 `frequency_cooldown` (exit 2)
WeChat 触发了风控（200013）。**等几个小时再试**，不要循环重试——会延长 cooldown。这段时间可以跑 `hive-mp sync --repair`（不调用 WeChat API）补未完成的文章。

### 国内用户访问 `{{SITE}}` 慢
报告给我们；分发服务器有国内备案，理论上应该比 GitHub 快。

---

## 备用：从 GitHub 直装

如果 `{{SITE}}` 的 marketplace 不可达，或者用户是开发者想用最新源码版本，可以走 GitHub 直装。**这条路对国内用户不友好（GitHub 慢），优先用 marketplace。**

```bash
# 方式 A：从 GitHub Release 装（版本固定，推荐）
pipx install https://github.com/<org>/hive-mp-cli/releases/download/v0.1.0/hive_mp_cli-0.1.0-py3-none-any.whl

# 方式 B：从 main 分支装（永远最新，本地需要 git）
pipx install git+https://github.com/<org>/hive-mp-cli
```

国内用户走 GitHub 时 PyPI 依赖仍可走清华源：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    pipx install https://github.com/<org>/hive-mp-cli/releases/download/v0.1.0/hive_mp_cli-0.1.0-py3-none-any.whl
```

Chromium 仍要单独装（同上的 npmmirror 镜像逻辑）。Skill 包同理从 GitHub Release 下：

```bash
mkdir -p ~/.claude/skills/hive-mp-cli/
curl -L https://github.com/<org>/hive-mp-cli/releases/download/v0.1.0/hive-mp-cli-skill.tar.gz | \
    tar -xC ~/.claude/skills/hive-mp-cli/
```
