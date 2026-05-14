# hive-mp-cli — 更新指南

## 给人看的

复制下面这段给你的 AI Agent：

```
帮我更新 hive-mp-cli：{{SITE}}/install/hive-mp-cli-update.md
```

---

## 给 AI Agent 看的

### 你的目标

把用户的 hive-mp-cli 升级到最新版，验证 `hive-mp doctor` 仍然跑通。

### Step 1 — 探测网络环境

跟 install.md 同样的逻辑：判断用户是否在中国大陆，决定要不要走清华 PyPI 源 + npmmirror。

### Step 2 — 升级 CLI

```bash
pipx install --force {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl
```

`--force` 让 pipx 覆盖装。国内用户：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    pipx install --force {{SITE}}/packages/hive-mp-cli/latest/hive_mp_cli-py3-none-any.whl
```

验证：

```bash
hive-mp --version
```

### Step 3 — 升级 Chromium（如果需要）

Playwright 版本升级时，新的 Playwright 可能要求新的 Chromium 版本。如果 `hive-mp doctor` 提示 chromium 缺失，重跑：

```bash
# <GLOBAL>
pipx run --spec hive-mp-cli playwright install chromium

# <CN>
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ \
    pipx run --spec hive-mp-cli playwright install chromium
```

### Step 4 — 自检

```bash
hive-mp doctor
```

`chromium` / `disk` 是 ✅ 就 OK。`login` 这时可能因为 token 过期是 ❌，提示用户跑 `hive-mp login` 重扫即可。

### Step 5 — 升级 Skill（可选）

如果用户之前装了 skill：

```bash
# Claude Code
curl -L {{SITE}}/skills/hive-mp-cli.tar.gz | tar -xC ~/.claude/skills/hive-mp-cli/

# Cursor / OpenClaw — 换对应路径
```

### 数据兼容性

`~/.hive-mp/` 下的所有数据（accounts.json / articles.db / token.json / 已下载的 markdown）都是**向前兼容**的，升级不会丢数据。SQLite schema 升级时 CLI 会自动 migrate。

如果某次升级出了问题想回滚，重装上一版即可：

```bash
pipx install --force {{SITE}}/packages/hive-mp-cli/0.0.X/hive_mp_cli-0.0.X-py3-none-any.whl
```

（如果你不知道历史版本号，问用户或者查 {{SITE}}/packages/hive-mp-cli/）

---

### 备用：从 GitHub 直装

如果 marketplace 不可达，从 GitHub Release 升级：

```bash
pipx install --force https://github.com/xavierliang/hive-mp-cli/releases/latest/download/hive_mp_cli-py3-none-any.whl
```

`releases/latest/download/<filename>` 是 GitHub 自动维护的"最新版"重定向。国内用户走 GitHub 较慢，**优先用 marketplace 主路径**。
