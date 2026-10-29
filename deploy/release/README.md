# TFGM MCP v0.1.0 预览版

此部署包不需要本机安装 Bun、Python 或 RAGFlow。需要 Linux amd64、Docker Engine + Compose v2、OpenSSL、curl、unzip、sha256sum，以及足够存放镜像和解压知识库的磁盘空间。镜像仅提供 linux/amd64，不宣称支持原生 ARM64。

## 下载与安装

从同一个 GitHub Release 下载：

- tfgm-mcp-v0.1.0-deploy.zip
- tfgm-mcp-v0.1.0-linux-amd64.tar.gz
- 知识包分片由部署包中的 download-knowledge.sh 自动下载
- SHA256SUMS

在下载目录校验并安装：

```sh
sha256sum --check --ignore-missing SHA256SUMS
unzip tfgm-mcp-v0.1.0-deploy.zip
docker load -i tfgm-mcp-v0.1.0-linux-amd64.tar.gz
cd tfgm-mcp-v0.1.0
./download-knowledge.sh
mkdir -p knowledge
unzip tfgm-library-r1.zip -d knowledge
./prepare.sh 192.168.1.100  # 替换为实际访问 IPv4 或域名
# 多实例部署时修改 .env 的 COMPOSE_PROJECT_NAME 和 TFGM_MCP_PORT
docker compose up -d --wait
docker compose ps
```

部署包使用预构建镜像，不在启动时编译或下载知识数据。知识库只读挂载，不写入镜像。初始化脚本生成 90 天自签证书和随机令牌；重复运行保留现有文件。更改域名时需重新准备匹配证书，不会自动覆盖。

若主机已存在同名 Compose 项目，启动前修改 .env 中 COMPOSE_PROJECT_NAME。默认监听所有网卡的 26511 端口。MCP 地址为 `https://实际地址:26511/mcp`，请求头 `Authorization: Bearer <secrets/mcp-token 文件内容>`。不要把真实令牌粘贴到公开渠道。

客户端必须信任 tls/cert.pem；生产环境可替换为受信任证书，但证书仍需覆盖 127.0.0.1 供内置健康检查使用（或者调整健康检查实现）。不要关闭 TLS 验证。镜像健康检查会验证 HTTPS 和认证。

## 工具与范围

默认 8 个离线工具，提供版本、文档关键词检索、原文、物品、制作配方、用途、配方详情及图片。0.13.15 收录 140426 条配方；0.13.17 有 1303 篇玩家文档，不能混用版本。没有完整生产路线规划能力，缺失配方条件保持未知。FTS5 是关键词检索，不是向量检索。

## 可选共享 RAGFlow

与 MCP 容器独立部署。默认 config/ragflow.json 为 enabled=false。要启用，参考 ragflow.example.json，设置外部 HTTPS 根地址、apiKeyFile、版本到 dataset IDs 的映射；将 key 放入 config/ragflow-api-key，权限 0600。文件在容器内对应 /run/config/ragflow-api-key。自签上游可以配置 caFile。配置后执行 `docker compose restart`。

增加的 kb_search_semantic 调用外部 RAGFlow，可能消耗其 embedding/rerank 服务配额；不会自动上传本地文档。外部服务不可用不影响 8 个离线工具。

## 运维

```sh
docker compose logs --tail 100
docker compose restart
docker compose down
```

日志按 10 MiB × 3 轮转。停止和删除容器不会删除宿主 knowledge、config、secrets、tls。更新知识包时先校验新包，停止服务并切换挂载目录后再启动，保留旧包回滚。不要覆盖正在查询的 SQLite。

本包程序许可见 LICENSE；第三方知识和媒体来源见 DATA-SOURCES.md，不因打包而变更其权属。

知识包以 64 MiB 分片发布。下载脚本校验每片及合并后的完整 ZIP；重跑跳过已校验分片。合并后可删除 downloads 内分片节省空间。校验值用于完整性检查，不替代可信发布来源。
