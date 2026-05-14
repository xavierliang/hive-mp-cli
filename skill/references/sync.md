# sync — 同步公众号文章

## 基本用法

```bash
hive-mp sync                              # 同步所有订阅的公众号
hive-mp sync "<公众号名>"                  # 只同步一个
hive-mp sync "<公众号名>" --pages 1        # 只拉第 1 页（最近 ~10 篇）
```

## 给 Agent 的预期说明

**别加 `--json`**——sync 默认就把每篇文章的进度逐行打到 stdout，自然语言，你读得懂。`--json` 会把整个过程憋到最后一坨 JSON，反而让你看不到进度。

**单次耗时**：`--pages 1`（10 篇文章左右）通常 **2-5 分钟**，反爬 sleep 占大头，**这是设计**——不要试图加速、不要超时杀。

**两种使用姿势都行**：

- **盯着看**：你的工具如果支持流式读取 stdout（Claude Code Bash tool 默认就是），每篇 ✓/✗ 会实时出现。最后一行 `→ syncing ... done new=X existing=Y ...` 表示结束。
- **扔了等**：直接调用、不监控、命令返回后看完整输出。也 OK，数据是 per-article commit，中间被杀都不丢已写入的文章。

## 两种模式

| 模式 | 命令 | 说明 |
|------|------|------|
| **web** (默认) | `--mode web` | 列表用 HTTP，文章正文用 Playwright 浏览器抓。**对反爬鲁棒，推荐** |
| **api** | `--mode api` | 全 HTTP。快，但文章正文经常被风控拦 |
| **no-browser** | `--no-browser` | 只拉元数据，不抓正文。用于试探"还有多少新文章" |

## --repair：修复未完成

定期 sync 的过程中，**正文抓取失败**会把 `has_content=0` 写进数据库（元数据有了，markdown 文件没生成）。原因可能是：

- WeChat 风控临时拦截
- Playwright 页面渲染超时
- 网络抖动

`--repair` 只对这些 `has_content=0` 的文章重试正文抓取，**不调用 WeChat API**——所以即使 token 过期也能跑：

```bash
hive-mp sync "<公众号名>" --repair --json
# → {"<名>": {"new": 0, "existing": 0, "repaired": 7, "failed": 1, "skipped_dead": 2, ...}}
```

每篇文章最多重试 `MAX_FETCH_ATTEMPTS=3` 次，超过就标记 `skipped_dead`，不再重试。

## --full：禁用去重

默认 sync 会跳过 `has_content=1` 的文章（已经抓全的）。加 `--full` 强制重抓：

```bash
hive-mp sync "<名>" --full
```

慎用——浪费配额、容易触发反爬。

## --since：增量

```bash
hive-mp sync "<名>" --since 2026-05-01
```

publish_time 早于这个日期的文章不入库。

## 频率控制（200013）

WeChat 的反爬代码。**触发后该 IP+账户被临时封**，CLI 会：

1. 当次 sync 立即停止（不继续拉后面的账户，否则延长封锁）
2. 把 cooldown 记录到 `~/.hive-mp/cooldown.json`
3. 之后短时间内的 sync 都直接 exit 2，不发请求

**正确的恢复姿势**：等几小时再试，期间用 `--repair` 补缺失的正文。

## 输出含义

```json
{
  "<公众号名>": {
    "new": 3,           // 新增（之前从未见过的文章）
    "existing": 7,      // 已有的、跳过的
    "repaired": 0,      // 这次填上了正文（之前 has_content=0）
    "failed": 0,        // 正文抓取失败的
    "skipped_dead": 0,  // 重试超过 3 次，放弃的
    "errors": [],
    "exit_code": 0
  }
}
```

## sleep 节奏

为了不触发反爬，CLI 在每个请求前后都 random sleep。**单账户单次 sync 5 篇文章大约 30-60 秒**。这是设计选择，不要试图加速。
