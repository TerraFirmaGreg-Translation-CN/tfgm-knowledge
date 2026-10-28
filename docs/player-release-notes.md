中文玩家知识包：从锁定版本的官方任务书和野外手册提取文档，附逐文件 SHA256、来源 commit、原始链接和许可证。未识别许可证的 Wiki 条目仅发布引用链接，不包含正文。

下载 `manifest.json` 即可通过仓库的 `knowledge:import --url <manifest链接>` 自动校验、上传和解析。默认预览导入 48 篇，`--profile full` 导入全部正文；二者使用不同的数据集。

这是知识包流程的预发布版本。文档不包含完整运行时配方，也不能替代对应版本的 EMI 或结构化查询工具。导入需要自行配置 RAGFlow 和 embedding 模型；知识包不包含 API 密钥。详情见仓库 `docs/player-knowledge.md`。
