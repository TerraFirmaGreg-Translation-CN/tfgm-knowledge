# TFGM 0.13.17 上游文档扩展分析

核验日期：2026-10-28。目标是提高游戏问答覆盖率，而不是增加代码文件数量。本轮按整合包 CurseForge 平台依赖文件核对上游标签，并保存了逐文件清单 `sources/upstream-review.json`。这些是基础模组作者的一手资料，但其默认行为不自动等于 TFGM 的最终行为。

## 已定位的正文增量

| 来源与固定版本 | 候选文件 | 能补充的问题 | 接入前处理 |
| --- | ---: | --- | --- |
| [GT CEu Modern v7.5.3-1.20.1](https://github.com/GregTechCEu/GregTech-Modern/tree/v7.5.3-1.20.1/docs/content/Gameplay) | 16 份英文 Markdown，含目录页 | 电力、线缆、变压器、发电机、流体管道、覆盖板、蒸汽系统、中央监控 | 仅选 Gameplay；默认矿脉、进度与锅炉数值需和 TFGM 覆盖核对；开发教程另存 |
| [Firmalife v2.1.28](https://github.com/eerussianguy/firmalife/tree/v2.1.28/src/main/resources/assets/tfc/patchouli_books/field_guide) | 31 份英文、29 份中文条目 JSON | 蜜蜂、温室、食品加工、面包、乳制品等 | 提取 Patchouli 正文；按条目与 TFGM 手册去重，中文优先、缺失时保留英文并标注 |
| [AE2 UELM forge/v15.5.6-uelm](https://github.com/AE2-Unofficial-Extended-Life-Modern/AE2-UELM/tree/forge/v15.5.6-uelm/guidebook) | 120 份英文 Markdown，含目录页 | 频道、子网、P2P、存储字节与类型、自动合成、接口、样板供应器、布局示例 | 保留解释与场景注释；解析 ItemLink，清理 GameScene 绘图参数；保留场景来源，不把图中接线关系凭空转成文字 |

合计 **196 份文件，不是 196 个互不重复的知识点**。Firmalife 的 60 份文件是双语版本；英文比中文多的路径为 `entries/mechanics/bread.json`、`entries/mechanics/dairy.json`，仍须核对中文其他条目和 TFGM 改写是否已覆盖。GT/AE2 目录页也不应单独算作实质问答文档。

版本证据来自已锁定整合包的 `pakku-lock.json`，对应依赖文件：

- `gtceu-1.20.1-7.5.3.jar`
- `Firmalife-1.20.1-2.1.28.jar`
- `appliedenergistics2-forge-15.5.6-uelm.jar`

GT 的 `docs/LICENSE` 是 CC0-1.0，不能只沿用仓库代码许可证；Firmalife 根 LICENSE 为 MIT。AE2 的 README 明确把 Text and Translations 列为 CC0；代码为 LGPLv3、纹理与模型为 CC BY-NC-SA 3.0，声音也有单独说明。因此优先提取文字，不把图像、模型或声音一起按 CC0 发布。来源许可证应按文档路径保存。

## TFGM 自身仍有可用内容

1. **物品与机器提示文本。** 当前已采集的 `kubejs/assets/*/lang/zh_cn.json` 和 TFG 拆分语言文件含工具用法、机器限制、装备效果等可读说明，玩家包尚未系统提取。下一步应把显示名与同一对象的提示组合成小文档，过滤界面词条和错误消息。`%s` 等运行时参数不能猜数值。
2. **Core 与配置中的机制证据。** 继续按问题提取营养、温度、重量、环境等规则，并记录代码位置、配置覆盖和版本。代码留在分析层，只有核验过的规则摘要进入问答层。
3. **官方在线野外手册。** [build.json](https://wiki.terrafirmagreg.team/modern/field-guide/build.json) 已为 0.13.17，发布标签 `site-fg-0.13.17-a6e3628`，可用于校验渲染结果及图示。已有整合包中英文手册各 95 个 entry；英文额外文件主要是模板，不能计为漏采正文。站点多语言页面数也不能计为独立知识量。
4. **官方在线任务书。** [build.json](https://wiki.terrafirmagreg.team/modern/quest-book/build.json) 为 0.13.17，适合作为已有任务正文与依赖关系的交叉校验，不重复导入一整套相同内容。
5. **官方配方书。** [build.json](https://wiki.terrafirmagreg.team/modern/recipe-book/build.json) 本轮仍为 0.13.15。保留来源与版本记录，不能作为 0.13.17 精确配方依据。精确配方需要同版本运行时 EMI 导出。

## 第二批候选与限制

| 来源 | 已知版本或状态 | 推荐用途 |
| --- | --- | --- |
| [TerraFirmaCraft](https://github.com/TerraFirmaCraft/TerraFirmaCraft) / [1.20.1 手册](https://terrafirmacraft.github.io/Field-Guide/20/en_us/) | TFGM Core 包含 TFC 源码；上游默认分支已是 1.21.x，尚未建立完整分叉对应关系 | 补基础概念与术语；以 TFGM 手册和 Core 为准，不直接采默认分支 |
| [Create](https://github.com/Creators-of-Create/Create) | 包内 6.0.8；文档版本映射待核对 | Ponder 场景说明、机械动力和物流；不能把场景 Java 直接当正文 |
| [Greate](https://github.com/GreateBeyondTheHorizon/Greate) | 包内 0.0.81；本轮查看分支而非匹配标签 | Create 与 GT 的整合改动，后续核对源码与提示；未发现成体系手册目录 |
| [Ad Astra](https://github.com/terrarium-earth/Ad-Astra) | 包内 1.15.21；精确文档快照待核对 | 氧气、太空生存与设备；星球进度和配方必须与 TFGM 覆盖核对 |
| [Jellies Modern](https://github.com/TerraFirmaGreg-Team/Jellies-Modern/tree/0.1.6) | 包内 0.1.6，有对应标签 | 水母相关数据和语言提示；与现有 TFGM 手册去重，README 不等于新增完整手册 |
| [CC:Tweaked](https://tweaked.cc/) | 当前 CurseForge 依赖输出没有对应平台文件，不能凭另一平台记录认定版本 | Lua 与外设 API；单独的程序开发知识域，确认安装版本后接入 |
| [FTB Quests](https://github.com/FTBTeam/FTB-Quests) | 工具与格式上游 | 解锁条件、任务字段语义的解析依据；不作为 TFGM 游戏攻略 |
| [Tools Modern](https://github.com/TerraFirmaGreg-Team/Tools-Modern) | 有 OresToFieldGuide、EMICategories、语言合并工具 | 借鉴转换流程及追溯生成过程；工具源码不作为玩家问答正文 |

Vintage、Magica 属于其他整合包，不纳入 Modern 的通用检索域。Discord Bot、Actions、打包发布工具等也不计入游戏文档数量。

## 接入顺序与检索规则

先补 TFGM 自身提示文本；再加入 GT、AE2 的概念和操作指南；接着加入去重后的 Firmalife 条目。默认配方、矿脉分布、机器数值和进度要求暂留审查层，直到与整合包覆盖完成比对。

每份文档至少记录：整合包版本、模组版本、仓库 commit、原文路径、语言、许可证、资料层级、覆盖核对状态。`installed-mod-version-matched` 只代表模组版本匹配，不代表 TFGM 行为已验证。

检索时同版本 TFGM 任务、手册、配置和运行时数据优先；基础模组文档用于补充解释。遇到冲突，不能让相似度分数替代来源优先级。英文原文可参与中文查询测试，不能未经测试就声称跨语言效果达标。

本轮清单是分析输入，不是 `sources/official.json` 的替代配置；现有解析器的 `dependency` 策略专用于 Core，不能直接给其他模组复用。自动接入前需增加按依赖文件解析标签的策略、文档级许可证处理和上述来源优先级。

## 本轮交付边界

固定版本候选清单已入仓库；正文下载至本地忽略目录 `.local/upstream-review/0.13.17/`，逐文件以 Git blob SHA-1 核验，并另存 SHA-256 下载报告。现有 r1 发布包和 RAGFlow 预览数据集不变。本轮没有把未经覆盖核对的基础模组数值混入玩家问答库，也未重新跑检索评测。
