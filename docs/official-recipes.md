# 官方配方站接入与 Agent 查询

> 本文保留早期按需缓存方式。当前 Agent 推荐使用[完整离线知识库](offline-knowledge.md)；此旧接口不是完整离线收录的证明。

数据源仅使用 [TFGM 官方配方站](https://wiki.terrafirmagreg.team/modern/recipe-book/) 已处理好的 JSON。无需安装导出器、启动游戏或抓取配方截图。

2026-10-29 核验：`build.json` 为 **0.13.15**，构建 `site-tfg-0.13.15-09bf39c`。`bundle.json` 声明 140,426 条配方；物品目录有 23,383 个 ID，中文名称表有 22,609 条记录。数量并非全量人工验证结果，也不等于当前已下载的配方数。

## 获取和更新

```bash
bun run knowledge:official sync --version 0.13.15
```

输出本地 manifest 路径：

```text
.local/official-recipes/tfg-0.13.15-09bf39c/manifest.json
```

首次只下载 bundle 元数据、物品目录和中文名称，随后按需读取物品反向索引及配方详情。原图保留官方 URL，不下载约 1.2 GB 的站点附件。同步结果隔离在“游戏版本＋官方 contentHash”目录，重复同步复用已核验的基础缓存。

每次下载新的详情前后都重新检查官方 `build.json`。上游构建发生变化时拒绝写入旧快照，需重新同步。已缓存的旧快照仍可查询。每个 JSON 缓存保存来源 URL、原始响应 SHA-256 和规范化内容 SHA-256；读取时校验内容。基础文件摘要记录在 manifest。站点不是不可变归档，保留本地快照才能保留已经查询过的旧内容。

指定 `--version 0.13.17` 不会自动降级到 0.13.15。本接口不与 0.13.17 的 RAGFlow 数据集隐式混合。

## 查询命令

```bash
# 中文／ID／官方搜索词查物品，多个候选交给 Agent 澄清
bun run knowledge:official search \
  --manifest .local/official-recipes/tfg-0.13.15-09bf39c/manifest.json \
  --version 0.13.15 石灰水

# 制作配方列表；direction=input 则查用途
bun run knowledge:official find \
  --manifest .local/official-recipes/tfg-0.13.15-09bf39c/manifest.json \
  --version 0.13.15 tfc:limewater --direction output

# 配方详情、原始槽位与图片链接
bun run knowledge:official get \
  --manifest .local/official-recipes/tfg-0.13.15-09bf39c/manifest.json \
  --version 0.13.15 tfg:mixer/limewater_from_flux
```

列表支持 `--offset`、`--limit`，最大每页 100 条。`--offline` 禁止联网，只能读取已经缓存的资源，缺失时明确报错，不把未缓存当作“没有配方”。名称表没有覆盖目录中所有 ID，已知准确 ID 时可直接查反向索引。

## Agent HTTP 接口

```bash
bun run knowledge:official serve \
  --manifest .local/official-recipes/tfg-0.13.15-09bf39c/manifest.json \
  --version 0.13.15 --port 20260
```

该命令前台运行，只监听本机 `127.0.0.1`；不是已经部署的公网服务。Ctrl+C 停止。OpenAPI 地址：`http://127.0.0.1:20260/openapi.json`。

| HTTP GET 路径 | 参数 | Agent 用途 |
| --- | --- | --- |
| `/v1/status` | `version` | 查询来源版本、构建与覆盖范围 |
| `/v1/items` | `version,q,limit` | 搜索物品名称和 ID |
| `/v1/recipes` | `version,item,direction,offset,limit` | 查询制作配方／用途索引 |
| `/v1/recipe` | `version,id` | 获取配方详情与图片链接 |

除 OpenAPI 外，每个请求必须明确指定匹配的 `version`，否则返回 400。`direction=output` 是制作方式，`direction=input` 是用途。返回的配方列表来自官方反向索引，不是根据配方图的 `displayId` 自行推断。

Agent 的典型调用顺序：`search_items` → 选择准确 ID → `find_recipes_or_uses` → `get_recipe`。OpenAPI 可用来封装 HTTP 工具；没有自动修改 Dify 或其他 Agent 的配置。容器或远程 Agent 的 `127.0.0.1` 并非本机，需要后续配置可达的代理地址，不能原样照填。

## 精确性边界

本接入提供查询，不提供多步路线计算。即使完整站点声明有 14 万余条配方，详情依然可能只是 EMI 展示数据。

- 不把遗漏的数量字段当作 1。
- 不把标签代表图标当作唯一原料。
- 不合并重复槽位、不把替代列表变为同时必需的原料。
- 原始 JSON 中缺少的耗时、电压、概率和执行条件保持未知。
- 图片使用官方实时 URL；站点更新后可能改变，不能保证图片链接永远指向旧版本。
- 404、上游不可用和未缓存不能解释为“该物品无配方”。

实例：石灰水查询返回 7 条制作相关记录，包括桶装流体倒出、Greate 搅拌、GT 搅拌与大桶。GT `tfg:mixer/limewater_from_flux` 展示数据给出 500 mB 水输入与 500 mB 石灰水输出，但助焊剂没有显式数量字段，且没有提供完整的机器运行条件。`route_calculation_supported` 因此为 false。

## 验收记录

2026-10-29：31 项代码测试通过。实查石灰水得到 7 条制作相关记录和 31 条用途记录，GT 搅拌与大桶两份配方详情均核对成功。临时 HTTP 服务的 OpenAPI、物品搜索、配方列表、配方详情均调用成功，0.13.17 请求被拒绝；验收后临时服务已关闭。测试没有宣称已经逐条核验 140,426 条配方。
