# tfgm-knowledge

从一手资料构建可追溯、按版本锁定的 **TerraFirmaGreg Modern（群峦格雷现代版）知识库**。

当前推荐入口：[完整离线知识库](docs/offline-knowledge.md)。已完整收录官方 0.13.15 配方附件并整合既有 0.13.17 玩家资料，查询无需访问官网或外部模型。

同步官方 GitHub 仓库，提取任务书、野外手册、Wiki、语言文件、配置和配方定义，输出离线 Markdown、JSONL、SQLite 全文索引及 ZIP。每条记录保留来源文件、commit、语言、许可证识别结果和版本关系。

## 快速开始

需要 **Python 3.11+、Git 和支持 FTS5 trigram 的 SQLite**。项目没有第三方 Python 运行依赖，推荐使用官方 Python 3.12。所有命令从仓库根目录执行。

```bash
git clone https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge.git
cd tfgm-knowledge

# 获取最新稳定版，锁定来源，同步并打包
python -m tfgm_knowledge update

# 或构建指定稳定版
python -m tfgm_knowledge update --version 0.13.17

# 查询最近一次成功构建
python -m tfgm_knowledge search 合金 --kind quest --language zh_cn
python -m tfgm_knowledge search "Animal Husbandry" --kind field-guide
```

GitHub API 可读取 `GH_TOKEN` 或 `GITHUB_TOKEN` 环境变量；不配置时使用匿名配额。令牌只发送到 GitHub API，不保存进锁文件或产物。定时工作流使用 GitHub 自动提供的只读令牌。

也可以分步执行：

```bash
python -m tfgm_knowledge validate
python -m tfgm_knowledge resolve --version 0.13.17
python -m tfgm_knowledge sync
python -m tfgm_knowledge build
python -m unittest discover -s tests -v
```

`build` 完全离线。`sync` 只下载文本来源，不执行上游脚本、不启动 Minecraft。需要换路径时，把全局参数放在子命令前：

```bash
python -m tfgm_knowledge --cache /tmp/tfgm-cache --output /tmp/tfgm-dist update
```

## 来源与版本

配置位于 [`sources/official.json`](sources/official.json)。

| 来源 | 锁定方式 | 用途 |
| --- | --- | --- |
| [Modpack-Modern](https://github.com/TerraFirmaGreg-Team/Modpack-Modern) | 稳定版 release tag → commit | 任务、手册、脚本、配置、语言、依赖 |
| [Core-Modern](https://github.com/TerraFirmaGreg-Team/Core-Modern) | 从整合包 `pakku-lock.json` 中的 Core JAR 版本匹配 tag | 自定义机制、TFC 分支、数据和源码 |
| [Wiki](https://github.com/TerraFirmaGreg-Team/Wiki) | `main` → commit | 中英文 Markdown 文档 |
| [Field-Guide-Modern](https://github.com/TerraFirmaGreg-Team/Field-Guide-Modern) | `main` → commit | 手册导出工具与元数据 |
| [QuestBook-Modern](https://github.com/TerraFirmaGreg-Team/QuestBook-Modern) | `main` → commit | 任务书导出工具与元数据 |
| [RecipeBook-Modern](https://github.com/TerraFirmaGreg-Team/RecipeBook-Modern) | `main` → commit | EMI 导出工具与元数据 |

默认平台是 `curseforge`。Pakku 锁文件中的不同平台可能锁定不同文件，构建器保留平台选择，不会静默改用另一平台。

任务和手册正文读取整合包发布快照。Wiki 及导出工具通常没有与整合包一一对应的标签，因此明确标为 `unversioned-snapshot`，`applicable_modpack_version` 为 `null`。

每次更新还检查三个官方在线站点的 `build.json`。网站版本落后时，报告标为 `version-mismatch`，不会把旧版导出数据混进当前版本。详细发现与入口见 [`docs/sources.md`](docs/sources.md)。

## 产物

每个完整构建位于 `dist/tfgm-<版本>-<构建ID>/`，并生成同名 ZIP：

```text
manifest.json          构建版本、来源与记录计数
sources.lock.json      六个来源的固定 commit、依赖和在线导出版本
dependencies.json      从 Pakku 提取的依赖文件及版本标识
inventory.json         采集文件与 SHA-256
report.json            覆盖范围、缺失翻译、引用问题及版本差异
NOTICE.md              上游内容权利说明
raw/                   已选取的文本资料及上游许可证文件
markdown/index.md      可读目录
markdown/*.md          文档、任务、手册、版本说明
records.jsonl          规范化完整记录，含原始结构数据
chunks.jsonl           AI 检索片段，含原记录 ID 与字符位置
knowledge.sqlite       全文索引与任务前置关系
```

`dist/latest.json` 指向最近一次成功构建，并记录 ZIP 的 SHA-256。原文快照和生成包均不提交 Git。

FTB 任务保留任务 ID、章节 ID、依赖、目标、奖励和原始 SNBT 解析结果。中英文文本按语言键解析，缺失翻译保留原键或明确标记英文回退；文本所用翻译文件也有来源记录。标题未提供时尝试使用任务目标名称，不会把内部 task ID 当物品名。

SQLite 使用 trigram 索引支持中英文检索；一个或两个字符的查询走子串查找。可通过 `--kind`、`--language` 限定范围。SQL 表和记录结构见 [`docs/data-model.md`](docs/data-model.md)。

## 自动更新

GitHub Actions 的 **Update knowledge** 工作流每天北京时间 **10:00** 检查一次，也支持手动指定稳定版。计划任务由 GitHub 调度，可能延迟。

工作流先运行测试，再解析版本、同步来源和构建，成功后上传 ZIP 与 `latest.json` 到本次运行的 Artifacts，保留 7 天。查看 Actions 的运行摘要可发现在线配方书、任务书或手册的版本差异。

同一 commit 和采集范围的源码缓存会复用。本地构建 ID 同时覆盖来源、配置、导出状态和解析器代码；无变化时复用已有成品。失败不会覆盖上次成功产物。源缓存有未提交修改时拒绝构建，请移除对应缓存目录后重新同步。

## v0.1 的覆盖范围

- 已实现：六个官方 Git 来源、中英文任务关系、手册正文、Wiki、配置、语言文件、源码配方定义、依赖清单、来源追踪、离线检索与自动打包。
- **尚未导入运行时 EMI 数据包**：目前只核验在线导出版本。源码中的配方定义不等于最终运行时配方，动态注册、删除和覆盖尚未求值。
- 图片、音视频、渲染后的多方块预览未打包；手册原始 JSON 中保留其引用和结构。
- 原始语言文件未必覆盖模组 JAR 内的全部译名；无法解析的任务文本会出现在报告中。
- 依赖清单已经自动提取，但没有递归同步所有上游模组仓库。
- 历史版本如果没有匹配的 Core 发布标签，解析将明确失败，不使用开发分支冒充。

本项目采集器代码采用 MIT。下载的文档、代码、翻译和资源保持各自上游权利；`NOASSERTION` 表示未识别出许可证，不表示内容可以任意再分发。本项目不是 TFG 官方团队维护的项目。

## 本地知识库开发环境

已提供隔离的 RAGFlow Docker 基础设施和自签 HTTPS 入口：

```bash
bun run mode:start
bun run mode:status
bun run mode:help
```

账户、模型配置、资源限制及清理策略见 [本地开发说明](docs/local-infra.md)。此环境与生产独立；基础设施启动后仍需配置 embedding 模型并选择文档入库。

## 按版本链接导入 RAGFlow

玩家文档知识包已支持固定流程：构建 → GitHub Release → manifest 链接校验导入 → 检索验收。首次预览默认 48 篇，完整包单独导入，模型和密钥留在本地。

```bash
bun run knowledge:connect
bun run knowledge:import --url https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge/releases/download/tfgm-0.13.17-r1/manifest.json
```

详见 [版本化玩家知识库流程](docs/player-knowledge.md)。

图文与配方试验：见 [媒体知识包流程](docs/media-knowledge.md)，支持原图关联、结构分层预览、同版本 EMI 子集查询，以及检索结果的媒体补充。

官方完整配方站接入：见 [官方配方查询与 Agent HTTP 接口](docs/official-recipes.md)。使用已经发布的 JSON、官方图片链接与按版本隔离的本地缓存，无需启动游戏。

Agent Skill：[tfgm-knowledge](skills/tfgm-knowledge/SKILL.md)。提供版本核对、离线文档检索、配方／用途查询及本地图片读取规则；Skill 不包含大型知识包。安装后可用 `$tfgm-knowledge` 调用。脚本支持 `--repo`、`--library` 或对应环境变量定位本地代码和数据。

## TypeScript / Bun MCP

新增离线 MCP 服务，供 AstrBot 等客户端查询版本、文档、物品、配方、用途及图片。运行 `bun run mode:mcp:start` 启动 HTTPS 服务，`bun run mode:mcp:status` 查看实际地址。数据构建仍沿用现有 Python 管道。

详细部署、工具边界与 AstrBot 配置见 [TypeScript MCP 说明](docs/typescript-mcp.md)，查询规程见 [AstrBot Skill](skills/tfgm-astrbot/SKILL.md)。

独立容器部署使用 `compose.mcp.yaml`，RAGFlow 作为可选外部服务配置，不随本服务部署。详见 [容器与共享 RAGFlow](docs/container-mcp.md)。

### 安装发布版

首个容器预览版为 `v0.1.0`。从 [GitHub Releases](https://github.com/TerraFirmaGreg-Translation-CN/tfgm-knowledge/releases) 下载部署 ZIP、linux-amd64 镜像归档、离线知识包与 SHA256SUMS，按部署包 README 校验并启动。部署机无需安装 Bun；初始化脚本会准备本机凭据，发布包不携带任何实际密钥。
