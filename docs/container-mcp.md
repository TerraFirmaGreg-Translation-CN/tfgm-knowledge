# 独立 TFGM MCP 容器与外部 RAGFlow

容器只运行 Bun MCP，SQLite 知识包只读挂载在 `/data/knowledge`。Compose 不创建 RAGFlow，也不依赖它的容器名称、数据库或 Docker 网络。未配置 RAGFlow 时提供原有 8 个离线工具；配置后额外提供 `kb_search_semantic`。

## 部署

使用 `Dockerfile.mcp` 和 `compose.mcp.yaml`。默认知识包为仓库下 `dist/offline/tfgm-library-r1`，TLS 和 MCP 令牌复用 `.local/mcp`。默认绑定宿主回环端口 26511，与本机 Bun 服务的 26510 分开。首次在新机器部署时，先准备知识包、包含 localhost/127.0.0.1/访问域名的证书及至少 32 字符的随机令牌；Compose 不自动下载知识包或生成凭据。可以用现有 `mode:mcp:start` 生成开发证书和令牌，然后停止本机服务。

```sh
docker compose -p YOUR_PROJECT-mcp -f compose.mcp.yaml up -d --build
docker compose -p YOUR_PROJECT-mcp -f compose.mcp.yaml ps
docker compose -p YOUR_PROJECT-mcp -f compose.mcp.yaml logs --tail 100
docker compose -p YOUR_PROJECT-mcp -f compose.mcp.yaml down
```

每个部署用唯一 project 名称，不要复用其他项目名称。可通过 shell 环境或 Compose `--env-file` 设置：

| 变量 | 用途 |
| --- | --- |
| TFGM_LIBRARY_DIR | 宿主机知识包绝对路径 |
| TFGM_MCP_PORT / TFGM_BIND_HOST | 宿主机端口 / 监听地址，默认 26511 / 127.0.0.1 |
| TFGM_ALLOWED_HOSTS | 允许的请求主机名，用逗号分隔，必须保留 127.0.0.1 供健康检查 |
| TFGM_TLS_DIR | cert.pem、key.pem 所在目录 |
| TFGM_TOKEN_PATH | MCP Bearer 令牌文件路径 |
| TFGM_EXTERNAL_CONFIG_DIR | 配置目录，包含 ragflow.json，可包含 API key 和 CA 文件 |
| TFGM_UID / TFGM_GID | 容器内文件访问身份，默认 1000:1000 |
| TFGM_MCP_IMAGE | 镜像名称 / 标签 |

Rootless Docker 下，宿主用户通常映射为容器 UID 0；若凭据为宿主用户所有且权限 0600，使用 `TFGM_UID=0 TFGM_GID=0`，不需要放宽私钥权限。容器仍运行于 rootless 用户命名空间，移除全部 capabilities、禁止提权，根文件系统只读。普通 rootful Docker 建议保留非 root UID 并正确配置挂载文件所有者。

容器使用 HTTPS 和 Bearer 认证；远程客户端需信任证书。对外服务建议使用稳定域名和受信任证书。健康检查只验证本地 MCP，不把共享 RAGFlow 故障当成本容器故障。日志轮转为 10 MiB × 3。当前 Compose 不包含自动镜像清理任务；构建前检查磁盘水位，更新后仅清理明确属于本项目且不用于回滚的旧镜像，不执行全局 prune。知识包不放入镜像或构建上下文。

## 配置共享 RAGFlow

默认挂载 `deploy/ragflow.json`，其中 enabled=false。该文件只是无密钥的默认模板；实际部署把配置保存在 Git 忽略的目录（例如 `.local/mcp-external`），通过 TFGM_EXTERNAL_CONFIG_DIR 挂载，不要把 API key 写入 deploy 或 Git。

示例 ragflow.json：

```json
{
  "enabled": true,
  "url": "https://ragflow.example.com",
  "apiKeyFile": "/run/config/ragflow-api-key",
  "timeoutMs": 15000,
  "datasets": {"0.13.17": ["TFGM_0_13_17_DATASET_ID"]}
}
```

在同一宿主目录创建 `ragflow-api-key` 纯文本文件（0600），填入 RAGFlow API key。自签服务可增加 `caFile: "/run/config/ragflow-ca.pem"` 并放置 CA；不会关闭证书验证。url 填服务根地址，不要追加 `/api/v1`。配置变更后重建容器实例以重新加载。

按 [RAGFlow 官方 Retrieval API](https://ragflow.io/docs/http_api_reference) 调用 `/api/v1/retrieval`，只发送管理员映射的 dataset IDs。Agent 无权传入任意 dataset ID、URL 或凭据。必须为不同游戏版本建立独立数据集，配置拒绝一个 dataset 同时属于多个版本；数据集内部内容版本的准确性仍由导入者保证。未配置版本不回退，响应中的 dataset 不在允许范围时整次拒绝。

外部结果标记 source_mode=external_ragflow，包含 dataset/document/chunk ID 与检索时间，不冒充本地快照。外部检索可能调用 RAGFlow 配置的 embedding 或 rerank 服务并产生费用。失败不自动切换或伪造结果；原有 kb_* 离线工具不受影响。

本轮不向共享 RAGFlow 上传文档，不替换其配置，不假设它部署在同一台主机。待 URL、API key 和各版本 dataset IDs 确定后启用。目前的本机进程入口仍默认仅提供离线工具；这里的外部配置由容器入口加载。

## 当前开发机实例

项目名 `tfgm-kb-4e8bbffb9af8-mcp`，Rootless Docker；本轮启动参数如下（无密钥）：

```sh
TFGM_UID=0 TFGM_GID=0 \
TFGM_BIND_HOST=0.0.0.0 \
TFGM_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.182.137 \
docker compose -p tfgm-kb-4e8bbffb9af8-mcp -f compose.mcp.yaml up -d --wait
```

地址 `https://192.168.182.137:26511/mcp`，令牌和证书仍使用 `.local/mcp/token` 与 `.local/mcp/certs/cert.pem`。复用旧进程凭据方便开发验收，生产部署应提供专用凭据。旧本机进程仍可通过原有 mode:mcp 命令管理；这些命令不会停止本容器。

运行容器验收：`TFGM_MCP_URL=https://127.0.0.1:26511/mcp bun scripts/check-mcp.ts`。
