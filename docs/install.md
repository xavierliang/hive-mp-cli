# hive-mp-cli — 安装指南

## 给人看的

复制下面这段给你的 AI Agent（Claude Code / Cursor / OpenClaw / Codex 等）：

```
帮我安装 hive-mp-cli：{{SITE}}/install/hive-mp-cli.md
```

Agent 会读这份指南把所有依赖装好，**你不用做别的**。装完后扫一次微信二维码就能开始用。

> 安全说明：这个工具只会在 `~/.hive-mp/` 下读写文件，不会动你别的目录，也不会装 sudo 权限的东西（除非你明确同意）。

**已经装过想升级？** 跑同一份指南即可——`pipx install` 加 `--force` 覆盖装就完成升级，`~/.hive-mp/` 下的数据向前兼容不会丢。

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

### 文档风格说明

下面每一步描述的是**目标和约束**，给的命令是**典型示例**。你（agent）了解自己运行的环境（OS、shell、用户已装什么、自己的 skill 目录在哪），按你的判断调整具体实现，只要满足"目标 + 约束"即可。

### 边界（必须守，无例外）

- **不要 `sudo`**——除非用户明确授权。装包用 `--user` 或 `pipx`，不要碰系统 Python。
- **不要在 agent workspace（当前工作目录）创建文件**——会污染用户项目目录。所有持久文件落 `~/.hive-mp/`，临时文件用 `/tmp/`。
- **不要修改 `~/.hive-mp/` 之外的用户文件**。
- **不要禁用防火墙、安全设置**或其他系统保护。
- **需要提升权限时，先告诉用户**让他决定，不要替他做主。

### 升级 vs 全新安装

- **全新安装**：按 Step 1 → Step 7 走（Step 8 可选）。
- **升级**：跳过 Step 2（pipx 已经有），Step 3 加 `--force` 覆盖装；Step 4 只在 `hive-mp doctor` 报 chromium 缺失时重跑；Step 6/7 不用做（已登录、已订阅）；Step 8 想刷新 skill 就重做一次。

### Step 1 — 探测网络环境

**目标**：判断用户在中国大陆还是海外，决定后续 Step 2/3/4 是否需要走国内镜像。

**判断依据**（任选其一，按你的偏好）：
- 系统 locale (`zh_CN`) 或时区 (`Asia/Shanghai`)
- 探测 `playwright.azureedge.net` 可达性
- 直接问用户

后续命令里出现的 `<CN>` / `<GLOBAL>` 标记，按用户位置选其中一条跑。

### Step 2 — 装 pipx（如果没有）

**目标**：让 `pipx` 可执行，且在用户的 PATH 里。

**约束**：不要走 `sudo`、不要碰系统 Python。

**典型做法**：
- 已有 pipx (`command -v pipx` 成功) → 跳过这一步
- 没有 → `python3 -m pip install --user pipx` 然后 `python3 -m pipx ensurepath`
- 国内用户加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- macOS Homebrew Python 报 `externally-managed-environment` (PEP 668) → 用 `--break-system-packages` 或 `brew install pipx`

**装完后**：确认 `pipx` 在当前 shell 的 PATH 里——具体怎么做按用户的 shell 处理（重开终端是最稳的兜底）。`pipx --version` 能跑就 OK。

### Step 3 — 装 hive-mp-cli

**目标**：`hive-mp --version` 能输出版本号。

**典型做法**：

```bash
# 全新安装
pipx install {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl

# 升级（覆盖装）
pipx install --force {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl
```

国内用户如果 pipx 拉传递依赖慢，给前面加 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。

### Step 4 — 装 Chromium（Playwright 浏览器）

**目标**：`hive-mp doctor` 的 chromium 检查能 ✅。

**约束**：
- 必须装到 hive-mp-cli 自己的 venv 里（用户机器上可能有多个 Python 环境，装错了 doctor 找不到）
- 中国大陆用户**必须**设环境变量 `PLAYWRIGHT_DOWNLOAD_HOST`，否则默认 CDN 在国内基本不通
- 大约 ~150MB 下载

**典型做法**：用 hive-mp-cli 的 Python 环境调 `playwright install chromium`：

```bash
# <GLOBAL>
pipx run --spec hive-mp-cli playwright install chromium

# <CN>
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ \
    pipx run --spec hive-mp-cli playwright install chromium
```

`npmmirror` 也慢的话，备用：`PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`。

> 装完落在 `~/Library/Caches/ms-playwright/`（macOS）或 `~/.cache/ms-playwright/`（Linux）。不需要你手动检查路径，让 doctor 验。

### Step 5 — 自检

```bash
hive-mp doctor          # 给用户看
hive-mp doctor --json   # 给你自己读
```

**判断标准**：
- `chromium` / `disk` 必须 ✅
- `login` / `accounts` 这时候是 ❌/⚠️ 是正常的（还没登录、还没订阅，下面几步会处理）

如果 `chromium` ❌，回 Step 4——很可能是 mirror env var 没设对，或者装到了别的 Python 环境。

### Step 6 — 引导用户首次登录

```bash
hive-mp login
```

会在终端打印 ASCII 二维码 + 保存 PNG 到 `~/.hive-mp/qrcode.png`。**告诉用户用手机微信扫**（不是 PC 微信），扫完在手机上确认登录。

完成后 `~/.hive-mp/token.json` 自动写入。登录态实际是否可用由微信服务端决定；`hive-mp status` 会做远端验证，失效后重跑 `hive-mp login` 即可。

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

**目标**：把 hive-mp-cli skill 装到你（agent）自己的 skill 目录，让以后用户说"同步 XX"这种话时你能直接路由到 CLI 命令，不用再读这份文档。

**约束**：
- skill 目录的位置由**你自己决定**——你比我们更清楚自己在哪查找 skill（Claude Code 是 `~/.claude/skills/`、Cursor / OpenClaw / 其他 agent 各自的约定不同）
- skill 包结构是 `SKILL.md + references/`，要作为一个整体放在 skill 目录的同一个子目录里

**典型做法**：

```bash
# 下载 tar 包
curl -fL {{SITE}}/skills/hive-mp-cli.tar.gz -o /tmp/hive-mp-cli-skill.tar.gz

# 解压到你的 skill 目录下的 hive-mp-cli/ 子目录
mkdir -p <你的-skill-目录>/hive-mp-cli/
tar -xC <你的-skill-目录>/hive-mp-cli/ -f /tmp/hive-mp-cli-skill.tar.gz
```

如果你不确定自己有没有 skill 机制，跳过这步，CLI 命令照样能用。

---

## Quick Reference

| 命令 | 作用 |
|------|------|
| `pipx install {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl` | 装 / 升级 CLI（升级加 `--force`） |
| `pipx run --spec hive-mp-cli playwright install chromium` | 装 Chromium |
| `hive-mp doctor` | 自检 |
| `hive-mp login` | 扫码登录 |
| `hive-mp refresh --if-expiring-within 48h` | 无扫码续期仍有效的登录态，可放进 cron / launchd |
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
- 多个 Python 环境共存时，可能装到了别的 Playwright 上。确保 `playwright install chromium` 是在 hive-mp-cli 的 venv 里跑的（典型方式：`pipx run --spec hive-mp-cli playwright install chromium`）

### `hive-mp login` 扫码后没反应
- 用手机微信扫，不是 PC 微信
- 扫完要在手机上点"确认登录"
- 二维码 60 秒过期，过期重跑

### `hive-mp sync` 报 `login_expired` (exit 3)
微信远端验证确认登录态失效。若登录态还没被服务端拒绝，可先跑 `hive-mp refresh`；已经失效时只能 `hive-mp login` 重扫一次。

### `hive-mp sync` 报 `frequency_cooldown` (exit 2)
WeChat 触发了风控（200013）。**等几个小时再试**，不要循环重试——会延长 cooldown。这段时间可以跑 `hive-mp sync --repair`（不调用 WeChat API）补未完成的文章。

### 国内用户访问 `{{SITE}}` 慢
报告给我们；分发服务器有国内备案，理论上应该比 GitHub 快。

---

## 备用：从 GitHub 直装

如果 `{{SITE}}` 的 marketplace 不可达，或者用户是开发者想用最新源码版本，可以走 GitHub 直装。**这条路对国内用户不友好（GitHub 慢），优先用 marketplace。**

```bash
# 方式 A：从 GitHub Release 装（版本固定，推荐）
pipx install https://github.com/xavierliang/hive-mp-cli/releases/download/v0.1.0/hive_mp_cli-0.1.0-py3-none-any.whl

# 方式 B：从 main 分支装（永远最新，本地需要 git）
pipx install git+https://github.com/xavierliang/hive-mp-cli

# 升级走同样的 URL，加 --force
pipx install --force https://github.com/xavierliang/hive-mp-cli/releases/latest/download/hive_mp_cli-py3-none-any.whl
```

国内用户走 GitHub 时 PyPI 依赖仍可走清华源：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    pipx install https://github.com/xavierliang/hive-mp-cli/releases/download/v0.1.0/hive_mp_cli-0.1.0-py3-none-any.whl
```

Chromium 仍要单独装（同上的 npmmirror 镜像逻辑）。Skill 包同理从 GitHub Release 下：

```bash
curl -fL https://github.com/xavierliang/hive-mp-cli/releases/download/v0.1.0/hive-mp-cli-skill.tar.gz \
    -o /tmp/hive-mp-cli-skill.tar.gz
mkdir -p <你的-skill-目录>/hive-mp-cli/
tar -xC <你的-skill-目录>/hive-mp-cli/ -f /tmp/hive-mp-cli-skill.tar.gz
```
