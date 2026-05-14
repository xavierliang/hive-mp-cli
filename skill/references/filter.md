# filter_rules.yaml — HTML 噪音过滤

WeChat 公众号文章常带推广区块（"点赞 / 在看 / 关注 / 分享 / 打赏"）。在 HTML → markdown 转换**之前**剔除掉，能让产出的 markdown 更干净。

## 启用

在 `~/.hive-mp/filter_rules.yaml` 创建文件即可生效。**文件不存在时不过滤**。

修改即时生效，下一次 sync 就用新规则，不需要重启。

## 完整示例

```yaml
global:
  # CSS 选择器（用 BeautifulSoup .select()）
  remove_selectors:
    - ".reward_area_personal_new"
    - "#js_profile_qrcode"
    - "section[data-tools='点赞']"

  # 按元素 id 移除
  remove_ids:
    - "js_share"

  # 按 class 名移除（不需要 . 前缀）
  remove_classes:
    - "rich_media_tool"

  # 正则替换（re.sub(pattern, '', html, flags=DOTALL)）
  remove_regex:
    - '<p[^>]*>关注我们[^<]*</p>'

accounts:
  # 针对特定公众号的额外规则（与 global 合并，不是替换）
  "阮一峰的网络日志":
    remove_selectors:
      - "p.author-promo"
  "技术博客 XX":
    remove_classes:
      - "promo-banner"
```

## 合并语义

- `accounts.<name>` 块**追加**到 `global`，不是替换
- 用 accounts.json 里的 `name` 字段匹配（不是 biz_id）

## 调试

跑一次 sync，看产出的 markdown 是否还有不想要的内容。有就把对应的 CSS 选择器加进 `remove_selectors`。**先用 selector 试，不行再上 regex**。

## 顺序

1. 解析 HTML → BeautifulSoup
2. 跑 `remove_selectors` + `remove_ids` + `remove_classes`
3. 把 HTML 序列化回字符串
4. 跑 `remove_regex`
5. 交给 markdownify 转 markdown

所以 selector 类规则比 regex 优先；regex 会作用在已经 selector 清洗过的 HTML 上。
