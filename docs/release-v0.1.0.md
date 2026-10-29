# TFGM MCP v0.1.0（预览版）

首次提供可以独立安装的 TFGM 离线知识查询服务。下载部署包、容器镜像归档和知识包后，可在 Linux amd64 机器部署，无需安装 Bun 或本地 RAGFlow。

- 8 个离线 MCP 工具：版本、文档、物品、配方、用途和图片查询。
- 0.13.15 收录 140426 条配方；另有 0.13.17 的 1303 篇玩家文档，严格区分版本。
- 可选接入独立的共享 RAGFlow，配置后增加语义检索工具。默认关闭，不自动导入数据。
- 知识包只读挂载，提供 HTTPS、Bearer 认证、健康检查及日志轮转。
- 部署包提供初始化脚本、挂载配置、使用说明和第三方数据来源说明。

## 下载

- `tfgm-mcp-v0.1.0-deploy.zip`：初始化脚本和 Compose 配置。
- `tfgm-mcp-v0.1.0-linux-amd64.tar.gz`：容器镜像，使用 `docker load -i` 导入。
- `tfgm-library-r1.zip.partNNN`：离线知识包分片，总计约 1.47 GB。部署包中的 `download-knowledge.sh` 自动下载、校验并合并为 ZIP，再解压至 knowledge/。
- `tfgm-library-r1.zip.json`：知识包摘要和版本格式信息。
- `SHA256SUMS`：Release 附件校验值。

安装前校验附件，按部署包 README 操作。镜像以 Release 附件提供，本版未发布到 GHCR。初始化生成的自签证书需要客户端信任；私钥和 API key 不包含在发布包中。

## 已验证与限制

类型检查、35 项 Python 测试、8 项 TypeScript 测试，以及真实容器的配方、图片、版本隔离与 HTTPS 验收。外部 RAGFlow 使用模拟接口验证；公共实例尚未配置。AstrBot / MCPHub 的实际对话接入仍需部署者验收。

本版只提供 linux/amd64 镜像；文档检索默认是关键词检索，不是向量检索。没有完整路线规划，缺失数量、能耗等参数不会自行补齐。服务版本 v0.1.0 与游戏版本 0.13.15 / 0.13.17 是不同概念。

第三方文本和媒体的权属、许可不因本项目打包而变更，参见部署包 DATA-SOURCES.md。GitHub 自动提供的源代码归档不包含知识数据库。
