#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
host=${1:-localhost}
if [[ ! "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; then
  echo '用法：./prepare.sh <访问域名或 IPv4 地址>（不含协议或端口）' >&2; exit 1
fi
for cmd in docker openssl; do command -v "$cmd" >/dev/null || { echo "缺少命令：$cmd" >&2; exit 1; }; done
docker compose version >/dev/null
if [[ ! -f knowledge/manifest.json || ! -f knowledge/knowledge.sqlite ]]; then
  echo '请先将 tfgm-library-r1.zip 解压至当前目录的 knowledge/ 下。' >&2; exit 1
fi
umask 077
mkdir -p secrets tls config
[[ -f secrets/mcp-token ]] || openssl rand -hex 32 > secrets/mcp-token
if [[ ! -f tls/cert.pem && ! -f tls/key.pem ]]; then
  san='DNS:localhost,IP:127.0.0.1'
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then san+=",IP:$host"; else san+=",DNS:$host"; fi
  openssl req -x509 -nodes -newkey rsa:2048 -days 90 -keyout tls/key.pem -out tls/cert.pem \
    -subj '/CN=tfgm-mcp' -addext "subjectAltName=$san" >/dev/null 2>&1
elif [[ ! -f tls/cert.pem || ! -f tls/key.pem ]]; then
  echo '证书和私钥不完整；请修复 tls/，脚本不会覆盖现有文件。' >&2; exit 1
fi
[[ -f config/ragflow.json ]] || printf '{"enabled":false}\n' > config/ragflow.json
if [[ ! -f .env ]]; then
  identity_uid=$(id -u); identity_gid=$(id -g)
  security_options=$(docker info --format '{{json .SecurityOptions}}')
  if [[ "$security_options" == *rootless* ]]; then identity_uid=0; identity_gid=0; fi
  cat > .env <<ENV
COMPOSE_PROJECT_NAME=tfgm-mcp
TFGM_MCP_IMAGE=tfgm-knowledge-mcp:v0.1.0
TFGM_LIBRARY_DIR=./knowledge
TFGM_TLS_DIR=./tls
TFGM_TOKEN_PATH=./secrets/mcp-token
TFGM_EXTERNAL_CONFIG_DIR=./config
TFGM_BIND_HOST=0.0.0.0
TFGM_MCP_PORT=26511
TFGM_ALLOWED_HOSTS=localhost,127.0.0.1,$host
TFGM_UID=$identity_uid
TFGM_GID=$identity_gid
ENV
fi
printf '初始化完成，现有凭据与配置均保留。\n检查 .env 后运行：docker compose up -d --wait\n令牌：secrets/mcp-token（不会打印）\n客户端需信任：tls/cert.pem\n更换访问域名时需同时更新证书和 TFGM_ALLOWED_HOSTS。\n'
