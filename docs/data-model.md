# 数据模型

## 完整记录 `records.jsonl`

每行一个 JSON 对象：

| 字段 | 含义 |
| --- | --- |
| `id` | 来源 ID、文件、条目 ID、语言生成的稳定标识 |
| `kind` | `quest`、`quest-chapter`、`field-guide`、`document`、`recipe-definition`、`tag-definition`、`language`、`configuration`、`source-code`、`data`、`export-tool`、`release` 或 `unparsed-data` |
| `title`, `text` | 可读标题和搜索文本 |
| `language` | `en_us`、`zh_cn` 或未确定的 `und` |
| `source_id`, `source_path`, `source_url`, `commit` | 来源与固定 commit 的文件链接 |
| `license` | GitHub 元数据识别结果；未识别时为 `NOASSERTION` |
| `context_modpack_version` | 本次构建围绕的整合包版本 |
| `applicable_modpack_version` | 确认关联的整合包版本；未确认时为 `null` |
| `version_relation` | `release-matched` 或 `unversioned-snapshot` |
| `content_sha256` | 搜索文本的 SHA-256 |
| `data` | 原始 JSON、任务结构或类型专用数据 |

`recipe-definition` 仅代表静态源码定义；不能作为运行时完整配方集。

任务 `data` 保留：`quest_id`、`chapter_id`、`chapter_file`、`dependencies`、`raw`、`localized`、`translation_sources`、`translation_fallbacks`、`missing_translation_keys`。依赖可以指向任务或章节，具体组合条件仍保留在 `raw` 中，边表不替代 FTB 的解锁求值器。

## 检索片段 `chunks.jsonl`

保留来源与版本字段，增加 `record_id`、`char_start`、`char_end`。`text` 是对应完整记录文本的切片；位置按 Python Unicode 字符计算，不是 UTF-8 字节或模型 token。默认最多 1,800 字符，重叠 160 字符。

## SQLite

- `records(id, kind, language, title, source_url, payload)`：完整记录。
- `search`：FTS5 trigram 全文索引，字段为 `id`、`title`、`text`。
- `quest_edges(quest_id, dependency_id)`：去重后的任务前置边，按整合包版本隔离在各构建中。

## 故障与一致性

来源解析必须全部成功才生成新锁文件；`update` 在成功构建后保存锁文件。同步使用不可变 commit 路径。SNBT 解析失败、重复任务 ID、必要正文缺失或 SQLite 校验失败会中断构建。未解析依赖和翻译缺失列入报告。

输出先写入临时目录，通过校验后生成 ZIP，再切换 `latest.json`。原文保存在 Git 快照中，`raw/` 是选定文件的 UTF-8 文本副本。
