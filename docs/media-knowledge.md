# 图文、结构与配方知识包

本地试验目标为 TFGM 0.13.17。独立配方站仍为 0.13.15，但官方野外手册发布 `site-fg-0.13.17-a6e3628` 的附件中已经包含**手册引用的同版本 EMI 展示导出**。来源和附件 SHA-256 固定在 `sources/media-0.13.17.json`；构建还检查附件内 `build.json`，不会接受跨版本附件。

## 本版覆盖

- 298 张按内容哈希去重的 PNG：手册图示与配方图。
- 583 份 Patchouli 结构记录：包括同一结构的多个变体，不能理解为 583 种不同机器。
- 132 条 EMI 配方展示记录：仅为手册引用子集，不是整合包全量配方。
- 1,303 篇玩家文档及配方文字摘要；预览导入其中 48 篇。

资源通过 `media.json` 与文档 ID 关联。图片保留原始 PNG，不调用视觉模型解释；文字说明取自同一手册页面。结构保留原始 `pattern`、`mapping`、页码和变体编号；离线预览可展示字符分层图，未推断世界坐标、朝向或未映射字符含义。

配方保留原始 EMI JSON、输入输出槽位、材料替代列表、标签、已明确给出的数量与图片。**未注明的物品数量不默认为 1**；没有导出的耗时、能耗、概率和执行条件均保持未知。`displayId` 只是标签当前展示的代表物品，不能当作唯一可用原料。没有完整标签展开时，按物品 ID 查询也不能保证找出所有接受该物品的标签配方。

原图内也可能有数量或图例，但本版没有 OCR 或视觉校验，不把图上的数字自动提升为精确字段。

## 构建与查看

先准备原有锁定资料 bundle，再下载固定附件：

```bash
mkdir -p .local/media-review
curl -fL --retry 2 \
  'https://github.com/TerraFirmaGreg-Team/Field-Guide-Modern/releases/download/site-fg-0.13.17-a6e3628/field-guide-site.tar.gz' \
  -o .local/media-review/field-guide-site.tar.gz

bun run knowledge:build --revision r2 --output dist/media-releases \
  --media-site .local/media-review/field-guide-site.tar.gz \
  --media-source sources/media-0.13.17.json

bun run knowledge:media-preview \
  --manifest dist/media-releases/tfgm-0.13.17-r2/manifest.json
```

最后一个命令输出可在浏览器直接打开的绝对 HTML 路径，无需前端服务。默认通过官方图片链接展示；完全离线查看时加 `--image-mode local`。预览展示高炉、大桶的图示和结构，以及全部 132 条配方图和已知字段。包内容改变时增加 revision，禁止覆盖已有不同内容的版本包。

## 精确配方查询

```bash
bun run knowledge:recipe \
  --manifest dist/media-releases/tfgm-0.13.17-r2/manifest.json \
  --id tfc:barrel/limewater

bun run knowledge:recipe \
  --manifest dist/media-releases/tfgm-0.13.17-r2/manifest.json \
  --item tfc:limewater --direction output
```

返回 JSON，包含版本、覆盖范围、原始字段和未知字段。查询支持配方 ID，以及输入／输出中的明确物品、流体或标签 ID；不是模糊自然语言搜索，也不是完整生产链规划器。下一层 Agent 可以把此命令封装为工具；本版未新增公开 HTTP 服务。

石灰水样例明确导出 500 mB 水输入和 500 mB 石灰水输出，以及助焊剂槽位；助焊剂的数量字段未给出，因此结构化查询保留未知。手册正文对数量有另外的解释，两者分别保留来源，不静默改写导出数据。

## RAGFlow 与 Agent 的职责

```bash
bun run knowledge:import \
  --url dist/media-releases/tfgm-0.13.17-r2/manifest.json --profile preview

bun run knowledge:query --report .local/imports/实际生成的报告.json \
  '高炉怎么搭建？'
```

RAGFlow 仍按文本切片。导入器先校验媒体索引、图片哈希、结构与配方文件及其引用，然后把资源缓存到 `.local/media/<包哈希>/`。导入报告保存文档与媒体的映射。

本项目的 `knowledge:query` 在取得 RAGFlow 命中文档后，会补上 `images`、`structures`、`recipes` 和 `unresolved_recipes`。图片优先返回官方站点 `url`，同时附上原图 SHA-256、来源附件、版本和本地备用路径；配方精确查询也返回图片链接。官方站点 URL 是可变地址，哈希固定的是下载时核验的快照，不能保证未来链接内容仍属于该版本。它们是**文档级候选关联**，不保证每张图片都对应当前命中的那一段文字；保留页码、说明和来源供 Agent 进一步筛选。外部 Agent 需要可访问的资源服务或自行解包，不能直接访问另一台机器的 `local_path`。

直接调用原生 RAGFlow 检索接口或使用其网页，并不会自动得到这层补充，也不会自动看懂图片。Agent 展示图片需要前端支持；如要解释图像内容，还需要视觉模型实际读取图片。

## 发布范围

当前 r2 仅为本地图文试验包。上游媒体可能涉及不同模组资产许可，来源和附件摘要已保留，尚未完成逐资产的再发布审查，因此没有把该媒体包上传到公开 Release。已有 r1 和其预览数据集保留。后续可将确认可发布的资产纳入同一 manifest 下载流程，其余仅保留出处链接。

## 本地验收

48 篇预览文档已解析为 376 个分块。高炉问题命中带有 1 张图片与 7 份结构记录的手册；石灰水问题命中带有 2 张图片、1 份结构和 3 条配方关联的大桶手册。精确查询确认石灰水的水输入为 500 mB，助焊剂数量仍保持“导出未注明”。这是检索与关联检查，不代表视觉理解或最终答案准确率。

验证结果：27 项代码测试通过；既有 8 个文本检索 smoke cases 全部命中；官方高炉图片链接已实际下载并核对 SHA-256。
