# 故障排查

## 先跑 doctor

任何问题先跑：

```bash
hive-mp doctor --json
```

看每个 check 的 status 决定下一步。

## Exit code 速查

| Code | 含义 | 处理 |
|------|------|------|
| 0 | 成功 | — |
| 1 | 用户错误 | 检查参数 / accounts.json |
| 2 | 网络或反爬 | 等待 + `--repair` |
| 3 | Token 过期 | `hive-mp login` 重扫 |

## Token 过期（exit 3）

WeChat token 大约 **2 小时**寿命。失效后任何调用 WeChat API 的命令都返回 exit 3。

```bash
hive-mp login
```

扫码完即可。**注意**：扫码用手机微信，不是 PC 微信。二维码 60 秒过期。

> Token 过期**不影响 `--repair`**——repair 只用 Playwright 抓公开 URL，不调 WeChat API。Token 过期的 24 小时窗口里依然可以补未完成的文章。

## 反爬触发 200013 / frequency_cooldown（exit 2）

WeChat 对单个 IP + 公众号做频率控制。**触发后**：

1. 当次 sync 立即终止（continue 会延长封锁，不要循环重试）
2. CLI 在 `~/.hive-mp/cooldown.json` 写一个 cooldown 标记
3. 短时间内的 sync 直接 exit 2，stderr 提示剩余等待秒数

**正确恢复姿势**：

- **等几个小时**（一般 2-6 小时，反爬严重时可能 24 小时）
- 期间用 `--repair` 补未完成正文（不调 WeChat API，不会被 200013 拦）
- **不要**循环重试

如果 cooldown 文件你确定可以清掉（比如换了网络），手动删 `~/.hive-mp/cooldown.json` 即可。

## 文章正文经常拿不到 (has_content 比例低)

`hive-mp doctor` 会报 `sync_health` warn。原因：

1. **反爬 JS 检测**：WeChat 越来越严，Playwright 注入的伪装可能被识别
2. **页面渲染超时**：网络慢 / 第三方脚本卡住
3. **文章被删**：fetch_status 会标 `deleted`，不计入失败

排查：

```bash
# 看最近几次 sync 的失败原因
sqlite3 ~/.hive-mp/articles.db \
  "SELECT title, fetch_status, fetch_attempts FROM articles WHERE has_content=0 ORDER BY fetched_at DESC LIMIT 10;"

# 看日志
tail -100 ~/.hive-mp/logs/hive-mp-$(date +%Y-%m-%d).log
```

如果是反爬，等几小时 + `--repair`。

## Chromium 装失败

国内默认 CDN 不通。设环境变量：

```bash
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ \
    pipx run --spec hive-mp-cli playwright install chromium
```

装完位置：
- macOS: `~/Library/Caches/ms-playwright/chromium-*/`
- Linux: `~/.cache/ms-playwright/chromium-*/`

如果装到了别的 Python 环境（系统多个 Python 共存），用 `pipx run --spec hive-mp-cli playwright install chromium` 强制走 hive-mp-cli 自己的 venv。

## accounts.json 损坏

CLI 检测到 JSON 解析错误时会把原文件改名成 `~/.hive-mp/accounts.json.corrupted-<ts>` 然后报错。**不会自动覆盖你的订阅列表**。

恢复办法：

```bash
# 看最近的备份
ls -la ~/.hive-mp/accounts.json.corrupted-*

# 编辑修复后改名回去
mv ~/.hive-mp/accounts.json.corrupted-1715000000 ~/.hive-mp/accounts.json
```

## 日志位置

```
~/.hive-mp/logs/hive-mp-YYYY-MM-DD.log
```

每天一个文件。bug 报告时把对应日期的日志附上。
