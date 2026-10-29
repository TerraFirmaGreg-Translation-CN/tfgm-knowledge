# 完整离线知识库

这是当前推荐的 Agent 数据入口。采集和构建时联网；查询只读本地知识包，不请求官方站点、RAGFlow 或外部 embedding 模型。

## 本次产物

目录：`dist/offline/tfgm-library-r1/`。

| 内容 | 数量／范围 |
| --- | --- |
| 知识文档 | 141,729 篇 |
| 官方配方 | 140,426 条，全部来自官方 0.13.15 发布附件 |
| 物品／流体目录 | 23,383 个 ID |
| 原始资源 | 316,627 个，包含 JSON、配方图、图标、标签、结构等 |
| 0.13.17 玩家资料 | 既有 r2 包的 1,303 篇任务、手册与配方子集文档 |
| 配方图片完整性 | 0.13.15 的 140,426 条配方均有对应图片 |

不同版本在同一数据库内分区，查询必须指定版本。0.13.17 玩家资料中的 132 条配方子集保留在正文和原始 `media.json` 中；本轮精确配方表和物品反向索引覆盖的是官方完整 0.13.15 包，不会自动跨版本回退。

目录中的三个文件即可迁移：

- `manifest.json`：版本、来源、覆盖统计和文件摘要。
- `knowledge.sqlite`：可读正文、全文索引、结构化配方、物品表、原始 JSON、图片及其他资源。
- `documents.jsonl`：全部知识文档的标准文本导出，便于导入其他知识库。

配方文档带有中文名称、输入输出槽位、材料标签、已知数量与来源。替代项较长时，正文只列前 12 个并提示其余项；原始结构化数据完整保留。图片是真实本地字节，不是只能联网打开的链接。

## 离线使用

```bash
# 关键词检索正文；支持中文，不需要外部模型
bun run knowledge:offline search --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 石灰水

# 搜索物品名称与 ID
bun run knowledge:offline items --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 石灰水

# 查制作方式；--direction input 查用途
bun run knowledge:offline find --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 tfc:limewater

# 读取精确原始字段，未导出的参数仍为未知
bun run knowledge:offline recipe --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 tfg:mixer/limewater_from_flux

# 查询已有 0.13.17 手册
bun run knowledge:offline search --library dist/offline/tfgm-library-r1 \
  --version 0.13.17 高炉

# 使用搜索结果的记录 ID 获取全文与媒体关联
bun run knowledge:offline document --library dist/offline/tfgm-library-r1 \
  --version 0.13.17 '<文档 ID>'

# 从数据库读取并保存图片，不访问网站
bun run knowledge:offline asset --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 recipes/tfg/mixer_limewater_from_flux.png \
  --output dist/offline/limewater.png
```

Agent 应使用关键词搜索，再读取匹配文档和结构化记录。当前检索使用 SQLite FTS5 trigram，短词用字面匹配；这是离线词法检索，不是语义向量检索，不能声称任意自然语言问题都能准确命中。若将来需要语义检索，必须使用本地 embedding 模型，不能继续依赖当前 RAGFlow 中配置的远程模型。

找不到资源时明确报“未收录”，没有任何联网补查逻辑。元数据中的官方链接仅用于追溯来源。

## 从官方附件构建

已固定的来源见 `sources/offline-recipes-0.13.15.json`，SHA-256 来自 GitHub Release asset digest。

```bash
mkdir -p .local/official-archives
curl -fL --retry 3 --continue-at - \
  'https://github.com/TerraFirmaGreg-Team/RecipeBook-Modern/releases/download/site-tfg-0.13.15-09bf39c/recipe-book-site.tar.gz' \
  -o .local/official-archives/recipe-book-0.13.15.tar.gz

bun run knowledge:offline build \
  --archive .local/official-archives/recipe-book-0.13.15.tar.gz \
  --source sources/offline-recipes-0.13.15.json \
  --player-pack dist/media-releases/tfgm-0.13.17-r2/manifest.json \
  --output dist/offline/tfgm-library-r1
```

构建流式读取完整附件，拒绝危险路径和链接；校验构建版本、实际配方数量及物品索引中的配方引用。失败时不发布半成品目录。已有输出目录不会覆盖，更新应使用新目录。

这是本次所选一手来源的完整离线化，不表示互联网上所有 TFGM 文档都已收录，也不表示官方展示数据包含完整运行条件。

## 打包、迁移与校验

```bash
bun run knowledge:offline verify --library dist/offline/tfgm-library-r1
bun run knowledge:offline pack --library dist/offline/tfgm-library-r1 \
  --output dist/offline/tfgm-library-r1.zip

# 复制 ZIP、旁边的 .zip.json 摘要文件和本项目代码到另一台机器后：
bun run knowledge:offline unpack --archive dist/offline/tfgm-library-r1.zip \
  --receipt dist/offline/tfgm-library-r1.zip.json \
  --output dist/offline/installed-library
```

实际 ZIP 为 1,468,748,753 字节，约 1.47 GB。解压后的数据库约 2.5 GiB、JSONL 约 194 MiB。运行仅需支持 FTS5 trigram 的 Python SQLite；Bun 仅作为命令入口，也可用 `python -m tfgm_knowledge.offline`。

当前包仅在本地生成，没有把原始模组媒体重新发布到公开 Release；代码、来源摘要和流程文档可以公开同步。

## RAGFlow 文档分包

```bash
bun run knowledge:offline export-ragflow --library dist/offline/tfgm-library-r1 \
  --version 0.13.15 --output dist/offline/ragflow-0.13.15
```

已生成 281 个分包，覆盖全部 140,426 篇配方文档，每包最多 500 篇。`catalog.json` 列出所有本地 manifest。每个包兼容已有 `knowledge:import`，需要导入整包时显式使用 `--profile full`；默认 preview 只取 8 篇。

分包中的 `offline.invalid` URL 仅供既有本地加载器取得文件名，不是已发布下载地址。图像和精确原始数据仍由配套离线知识库提供。分包不会自动执行 embedding，也没有将十四万篇文档上传到现有 RAGFlow。纯离线验收使用已构建的 SQLite 索引。

## 验收

禁用 Python socket 连接、create_connection 和 DNS 后，执行完整库校验、正文检索、物品搜索、制作／用途查询、精确配方读取及图片导出，全部通过。石灰水返回 7 条制作相关记录和 31 条用途；高炉手册保留 7 份结构记录和本地图片；跨版本配方查询被拒绝。

原始数据缺失的数量、能耗、耗时、概率不作补全。完整离线收录不等于完整合成路线计算，本版没有多步路线优化器。

35 项代码测试通过；281 个 RAGFlow 分包全部通过既有导入器格式与摘要验证。完整 ZIP 已实际安装到新的 `installed-library` 目录并通过整库校验；禁用网络后从该新目录读取配方和图片成功，不依赖旧采集缓存。
