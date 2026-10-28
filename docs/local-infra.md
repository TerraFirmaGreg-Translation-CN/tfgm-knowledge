# 本地 RAGFlow 开发基础设施

在仓库根目录运行，需要 Linux、Python 3.11+、Bun、OpenSSL、iproute2、Docker 和 Compose v2。Bun 只作为统一命令入口，没有额外 npm 依赖。

```bash
bun run mode:start
bun run mode:status
bun run mode:health
bun run mode:logs --follow
bun run mode:stop
```

`start` 首次生成配置、随机凭据和证书，拉取固定版本镜像并等待依赖、后端、首页和 HTTPS 就绪。再次运行时，健康的实例直接复用。`stop` 只停止核验属于当前仓库的容器，保留数据库、文档、索引和日志卷。不存在生产模式或自动连接生产环境的行为。

## 访问与账户

地址以 `mode:status` 显示的实际 HTTPS 端口为准，默认监听 `0.0.0.0`；局域网设备可访问面板显示的网卡地址，前提是主机防火墙允许。端口由仓库规范路径派生；同一仓库的符号链接共用身份，不同 checkout 独立。遇到占用最多尝试 32 个端口，不停止占用者。

证书在 `.local/certs/cert.pem`，浏览器首次访问会提示自签证书。脚本不会修改系统信任库。可将此证书导入浏览器的受信任证书列表；各设备需要分别导入。健康探测显式信任此证书并验证主机名和实例响应头，没有禁用 TLS 验证。网卡地址变化后，停止再启动会更新证书。

日常知识库账户为 `developer@tfgm.local`，随机密码保存在 `.local/credentials.json` 的 `user` 字段（邮箱也保存在 `user_email` 字段）。管理员 `admin@ragflow.io` 的密码在 `admin` 字段，仅用于后台管理；该版本禁止超级管理员访问普通工作区接口，不能用它登录日常知识库页面。用本地编辑器查看凭据，不要提交或发送该文件。首次启动先在容器内使用官方管理 API 设置并验证随机密码，再发布 HTTPS；该版本的 `ADMIN_DEFAULT_PASSWORD` 环境变量未被初始化代码采用，因此不依赖它。关闭公共注册。数据库和对象存储端口不发布到宿主机，只有 HTTPS 对外开放。

## 组件和资源

- RAGFlow `v1.0.0-rc2`，CPU，内存上限 4 GiB、2 CPU。
- Elasticsearch `8.11.3`，内存上限 1.5 GiB、堆 512 MiB。
- MySQL `8.0.40`、Silo（MinIO 兼容对象存储）、Kvrocks `2.16.0`、NATS `2.14.2`。
- Nginx `1.28.0-alpine` 提供自签 HTTPS，支持 WebSocket 和流式响应。

这是开发容量配置。大量解析与嵌入需要增加资源或使用专门服务器。未启动 GPU、代码执行沙箱、外部模型服务。镜像摘要锁定在 `infra/ragflow/images.json`，镜像版本及资源配置在 `scripts/mode.py`，官方运行模板保存在 `infra/ragflow/upstream/`。修改基础设施配置后用 stop/start 应用；升级 RAGFlow 前应单独备份和验证数据迁移，脚本不承诺数据库版本回退。

配置唯一入口为 Git 忽略的 `.local/mode.json`，保存版本、仓库身份、Docker daemon、实际端口和空间策略。凭据、证书、生成的 Compose 文件、运行记录与锁分开保存；敏感目录 0700、文件 0600。环境变量不覆盖持久配置。Docker context 必须与初始化时一致，不能借切换 context 误操作其他环境。不要移动仓库后直接复用 `.local`；身份不匹配会拒绝操作，原卷不会自动迁移或删除。

## 文档与检索测试

基础设施就绪不等于知识库已完成嵌入。登录后先设置自己的 embedding 模型，创建开发数据集，再上传少量 Markdown 测试解析与检索。问答还需要配置聊天模型。该部署不自动使用已有项目的 API 密钥，也没有默认付费模型调用。

TFGM 产物位于 `dist/latest.json` 指向的目录。优先选取中文任务书、野外手册和 Wiki 文档；不要把完整 ZIP、所有源码或所有配方定义直接上传到通用检索库。配方精确查询继续使用结构化工具，RAGFlow 用于文字知识检索。生产数据集、密钥和索引必须独立。

## 状态、日志与安全清理

```bash
bun run mode:help
bun --silent run mode:status --json
bun --silent run mode:health --json
bun run mode:clean --dry-run
bun run mode:clean
```

默认输出中文状态面板和分组帮助。TTY 使用语义颜色，`NO_COLOR` 或 `FORCE_COLOR=0` 关闭颜色，`FORCE_COLOR=1` 强制颜色。重定向仍是人类可读布局；只有 `--json` 输出机器数据，健康失败退出码为非零。JSON 调用不要使用 `logs`，它是原始日志流。

磁盘按调用用户可用空间计算使用率，Docker 根目录单独核验；同一文件系统明确标记。默认 75/85/92% 触发压力级别，70/78/85% 解除对应级别。准备镜像前和成功启动后执行维护；临界状态拒绝新部署，保留现有服务。首次部署镜像空间峰值未知，需要关注状态显示的磁盘水位。

当前使用上游共享镜像，不建立项目下载或构建缓存；因此没有能安全自动回收的 Docker 镜像。维护只允许清理登记在 `.local/cache-manifest.json`、属于当前仓库且闲置满 7 天的临时文件；未知使用时间保留宽限期。每轮最多 20 个文件、256 MiB、5 秒。预算为文件系统容量 1%，最多 2 GiB。预览完全只读；没有后台定时清理。源码、dist 知识库产物、上游同步缓存、凭据、证书和业务数据卷始终不属于清理候选，不调用全局 prune。

容器标准输出日志轮转为 10 MiB × 3；RAGFlow 应用文件日志也配置 10 MiB × 3。`mode:logs --follow` 查看持续日志。第一次镜像下载或数据库初始化耗时较长，启动失败后可再次运行 `start`，已下载镜像和数据继续保留。

NATS 的官方镜像不含 shell，而且 `nats-server --health-check` 在该标签下不是有效探测命令。本部署使用服务启动依赖，并由 RAGFlow `/api/v1/system/healthz` 的 `message_queue` 字段验证真实消息队列连接。

## 本机验收记录（2026-10-28）

实际 `mode:status` 摘录：

```text
运行状态    ● 运行正常
访问地址    https://127.0.0.1:20259
局域网      https://192.168.182.137:20259
健康检查    HTTPS、首页、后端与依赖均已就绪
```

实际 `mode:help` 摘录：

```text
服务管理
mode:start      启动并等待 HTTPS 和依赖就绪
mode:stop       停止本项目容器，保留全部数据

状态与排障
mode:status     查看状态、访问地址与空间
mode:health     检查真实服务健康，失败返回非零
```

通过 16 项单元测试和 6 个来源配置校验。实测 PTY 语义颜色、NO_COLOR、FORCE_COLOR、重定向纯文本和 JSON 可解析；40/80 列及停止/异常状态使用渲染夹具验证。实测本机/局域网 HTTPS、前端静态资源、管理员随机密码登录、上游默认密码拒绝、未信任证书和错误 SAN 拒绝、stop/start 后账户数据保留。后端返回 db、redis、doc_engine、storage、message_queue 全部 `ok`。尚未配置 embedding 模型或进行文档检索质量评估。

### 403 / Super user should not access the URL

若使用管理员登录普通页面，模型配置和首页统计会返回 403，前端还可能显示读取 `chats` 的错误。退出该账户，使用 `developer@tfgm.local` 登录；页面无法退出时可先用无痕窗口打开同一地址。`mode:start` 会将旧的仅管理员初始化记录迁移为双账户，并验证普通账户可读取模型配置、数据集、统计及聊天列表（含 `chats` 字段），全部成功才记录完成。不会重置已有同名账户密码。此修复已通过局域网 HTTPS 接口验收和 17 项单元测试。
