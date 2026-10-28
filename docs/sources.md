# 一手资料目录与核验记录

核验日期：2026-10-28。搜索引擎索引可能落后，以下版本以 GitHub API、仓库文件与在线 `build.json` 的直接读取结果为准。动态入口的当前值由每次构建重新记录。

## 首轮核验

| 对象 | 核验结果 |
| --- | --- |
| 整合包稳定版 | `0.13.17`，commit `32ba9f19d60bfc5b4148888fc84e50316b2b0fed` |
| Core 依赖 | `TerraFirmaGreg-Core-Modern-0.9.31.jar`，对应标签 `0.9.31` |
| 在线任务书 | `0.13.17`，与目标版本匹配 |
| 在线野外手册 | `0.13.16`，落后一个版本 |
| 在线配方书 | `0.13.15`，落后两个版本 |
| TFC 分支 | Core 源码包含 `src/main/java/net/dries007/tfc/`，本阶段直接纳入 Core 来源，不猜测另一个分支仓库 |

以上不是永久版本配置。锁文件固定本次解析所得 commit。

## 官方数据入口

- [整合包仓库](https://github.com/TerraFirmaGreg-Team/Modpack-Modern)：任务文件位于 `config/ftbquests/quests/chapters/*.snbt`。
- 任务翻译不仅在 `kubejs/assets/ftbquests/lang/*.json`，还分布于 `kubejs/assets/tfg/lang/{en_us,zh_cn}/quests/*.json`。采集范围包含两种布局。
- 手册正文位于整合包 `kubejs/assets/tfg/patchouli_books/field_guide/{en_us,zh_cn}/`。
- [核心模组](https://github.com/TerraFirmaGreg-Team/Core-Modern)：源码、`src/main/resources/data`、`src/generated/resources/data` 和语言文件。
- [Wiki 源码](https://github.com/TerraFirmaGreg-Team/Wiki)：`docs/modern/en_us/` 与 `docs/modern/zh_cn/`。旧 GitHub Wiki 不作为当前主来源。
- [手册导出项目](https://github.com/TerraFirmaGreg-Team/Field-Guide-Modern)、[任务书导出项目](https://github.com/TerraFirmaGreg-Team/QuestBook-Modern)、[配方书导出项目](https://github.com/TerraFirmaGreg-Team/RecipeBook-Modern)：与游戏内容分开标记为 `export-tool`。
- [版本发布](https://github.com/TerraFirmaGreg-Team/Modpack-Modern/releases)：构建目标、变更说明与发布附件。

## 官方站点版本清单

- [配方书 build.json](https://wiki.terrafirmagreg.team/modern/recipe-book/build.json)
- [任务书 build.json](https://wiki.terrafirmagreg.team/modern/quest-book/build.json)
- [野外手册 build.json](https://wiki.terrafirmagreg.team/modern/field-guide/build.json)
- [配方 bundle 索引](https://wiki.terrafirmagreg.team/modern/recipe-book/bundles.json)

配方导出仓库的 `ci/build.env` 指明上游导出工具链：

- [jmecn/minecraft-web-export](https://github.com/jmecn/minecraft-web-export)
- [jmecn/RecipeBook-React](https://github.com/jmecn/RecipeBook-React)
- [jmecn/emi-recipe-renderer](https://github.com/jmecn/emi-recipe-renderer)
- [jmecn/emi-bundle-optimize](https://github.com/jmecn/emi-bundle-optimize)

任务书对应工具：

- [jmecn/ftb-quest-export](https://github.com/jmecn/ftb-quest-export)
- [jmecn/QuestBook-React](https://github.com/jmecn/QuestBook-React)

这些地址来自官方构建配置，是后续接入运行时导出格式的直接线索。v0.1 不运行这些工具，不宣称已经导入 EMI 数据。

## 按依赖版本逐步扩展

| 来源 | 用途 |
| --- | --- |
| [TFC 源码](https://github.com/TerraFirmaCraft/TerraFirmaCraft) / [1.20.1 手册](https://terrafirmacraft.github.io/Field-Guide/20/en_us/) / [开发文档](https://terrafirmacraft.github.io/Documentation/) | 基础机制；TFG 分支和覆盖优先 |
| [GregTech Modern](https://github.com/GregTechCEu/GregTech-Modern) / [文档](https://gregtechceu.github.io/GregTech-Modern/) | 材料、电压、机器和配方体系 |
| [Create](https://github.com/Creators-of-Create/Create) | 动力、机器、物流 |
| [Greate](https://github.com/GreateBeyondTheHorizon/Greate) | Create 与 GregTech 整合 |
| [Firmalife](https://github.com/eerussianguy/firmalife) | 农业、食品和储藏 |
| [AE2 UELM](https://github.com/AE2-Unofficial-Extended-Life-Modern/AE2-UELM) | 对应分支的存储与自动合成说明 |
| [Ad Astra](https://github.com/terrarium-earth/Ad-Astra) | 太空机制 |
| [CC:Tweaked](https://tweaked.cc/) | Lua 与外设 API |
| [FTB Quests](https://github.com/FTBTeam/FTB-Quests) | 任务条件、字段和解锁语义 |

不根据名称自动把一个模组映射到某个仓库。应先从 `dependencies.json` 的平台项目 ID、版本文件和对应项目元数据确认，再添加匹配来源。
