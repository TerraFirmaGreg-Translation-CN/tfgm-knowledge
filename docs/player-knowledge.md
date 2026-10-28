# 版本化玩家知识库流程

第一版固定为游戏 **0.13.17 / 知识修订 r1**。公开内容为 1,171 篇中文文档：1,077 个任务、94 个野外手册条目；3 篇 Wiki 玩家文档仅保留链接，因为来源没有可识别的许可证。源码、配置 JSON、开发文档、历史更新日志、纯分类页面和缺少译文的任务不进入文字检索包。

知识包是公开可下载的文档产物，不是一个公开的 RAGFlow 服务。导入命令运行在你自己的环境中，模型和 API 密钥留在本地。

## 使用已发布的链接

先在本地 RAGFlow 的普通开发账户中配置默认 embedding 模型，然后连接：

```bash
bun run mode:start
bun run knowledge:connect
```

连接命令只在 `.local/ragflow.json` 尚不存在时创建 API Key。它从本地开发账户读取默认 embedding 模型，并保存 HTTPS 地址、证书路径和 API Key。已有有效配置会直接复用；不会输出密钥。首次连接会登录开发账户，因此浏览器可能需要重新登录一次；后续导入使用独立 API Key。

其他 RAGFlow 部署可自行准备该配置文件，字段为 `url`（不含 `/api/v1`）、`api_key`、`embedding_model`、可选 `ca`（自签 CA 绝对路径）。`RAGFLOW_API_KEY` 可覆盖配置文件的 API Key。当前适配并实际验证的服务版本是 `v1.0.0-rc2`，不能假定旧版本 API 相同。

```bash
bun run knowledge:import --url https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge/releases/download/tfgm-0.13.17-r1/manifest.json
```

默认只导入固定的 **48 篇预览文档**。命令先校验 manifest schema、ZIP 大小/SHA256、解压限制、安全路径和每个文件的 SHA256，全部通过才创建数据集。默认 General 解析、512 token 分块，使用配置文件指定的 embedding 模型。导入不调用聊天模型来改写原文，也不修改用户已有的 `TFGM` 数据集。

输出会显示解析进度、数据集 ID 和 `.local/imports/…json` 报告路径。文档上传成功不等于就绪：只有全部 `COMPLETED` 且有非零分块，报告才标记 `ready: true`。

使用普通开发账户登录 RAGFlow，进入 **Dataset**，选择名称以 `tfgm-0.13.17-r1-preview-` 开头的数据集，查看文档、分块并使用其检索测试入口。

## 断点恢复与完整导入

原样重跑导入命令会复用同一数据集、下载核对已有文档的实际内容、跳过已完成解析的文档，不会重新上传或重复嵌入。数据集名称由游戏版本、知识修订、范围、包内容摘要、目标地址和 embedding 模型共同确定。

网络失败或等待超时后，可重跑同一命令继续；解析失败先修复服务/模型，再加 `--retry-failed`。默认等待 900 秒，`--timeout 3600` 可延长等待。命令超时不会停止服务器上正在进行的任务。多个导入操作使用本地互斥锁，不能从多个工作目录同时管理同一数据集。

完整导入会创建另一个独立数据集，并产生额外 embedding 用量：

```bash
bun run knowledge:import --url https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge/releases/download/tfgm-0.13.17-r1/manifest.json --profile full --timeout 3600
```

## 查询与验收

将下面的 `<导入报告路径>` 替换为导入命令输出的路径：

```bash
bun run knowledge:query --report <导入报告路径> '锻铁炉只能烧什么燃料？'
bun run knowledge:evaluate --report <导入报告路径>
```

查询返回原文片段、标题、相似度和官方来源 URL，不把检索片段假装成模型生成答案。默认混合检索向量权重 0.7，取前五条，不启用重排。验收使用 `evaluations/preview-0.13.17.json` 的 8 个固定问题，检查预期文档及证据词是否进入前五条；结果在 `dist/evaluation-preview.json` 和 `.md`。这只是预览范围内的检索 smoke test，不代表全部游戏问题或最终生成答案的准确率。

## 构建与发布下一版

```bash
python -m tfgm_knowledge update --version 0.13.17
bun run knowledge:build --revision r2
```

输出为 `dist/player-releases/tfgm-0.13.17-r2/`：

- `manifest.json`：固定版本、修订、归档链接与校验值、文档索引、预览名单。
- `tfgm-0.13.17-r2-zh_cn.zip`：Markdown 文档、来源锁、许可证、归属声明和链接目录。

清理是确定性的，不调用 LLM：去掉 Minecraft 颜色标记、把 Patchouli 排版转换成文本、保留按键语义、把任务依赖 ID 补充为任务标题。任务目标数量不被解释为配方用量；图示、多方块布局不会凭空补写。

相同输入得到相同归档；相同版本修订已有不同内容时拒绝覆盖，应增加修订号。GitHub Actions 的 **Publish player knowledge pack** 工作流可手动选择游戏版本和新修订号，构建并发布 GitHub 预发布 Release；若标签已存在则拒绝覆盖。它不需要 RAGFlow 或模型密钥，也不会自动切换 Agent 正在使用的数据集。

固定 Release URL 便于复现。GitHub Releases 本身不是不可变存储；校验值用来检测传输/内容变化，不是发布者数字签名。不要把未知来源的 manifest 当成可信发布源。

## 后续版本策略

新游戏版本和新知识修订导入到新数据集，完成检索验收后再显式修改 Agent 的数据集 ID。第一版不自动激活新版本，也不删除旧数据集。配方、物品 ID 和任务依赖的精确工具接口仍属于独立结构化数据流程；原有原始知识包继续保留，玩家检索包并不取代它。

## 第一版实际验收

2026-10-28，本地预览数据集完成 48/48 篇解析，共 369 个分块。8 个固定问题的 Top-5 文档及证据词命中为 8/8；结果仅代表此预览测试集。使用用户已配置的 `Qwen/Qwen3-Embedding-8B`，未更换模型或获取其服务密钥。完整检索报告随 Release 提供。
