# 第三方版权与许可证声明（Third-Party Notices）

本仓库在以下开源项目代码的基础上修改 / 分发，各项目的版权与许可证信息汇总如下。
如有出入，以各源文件头部声明及许可证原文为准。

## 1. astrbot_plugin_denia_share（上游主体）

- 仓库：<https://github.com/xiaoxi2760/astrbot_plugin_denia_share>
- 版权：Copyright (c) 2026 xiaoxi2760
- 许可证：MIT（全文见仓库根目录 [LICENSE](../LICENSE)）
- 说明：本仓库在其代码基础上修改；除本声明与 README 外，其源文件头部的来源声明保持原样。

## 2. astrbot_plugin_rika_share（卡片渲染部分的上游）

- 仓库：<https://github.com/iris1598/astrbot_plugin_rika_share>
- 版权：Copyright (c) 2026 iris1598
- 许可证：MIT（全文见 [MIT-rika.txt](MIT-rika.txt)）
- 涉及文件：`core/card_renderer.py`（衍生自其卡片渲染模块，并已修改）。

## 3. f2（抖音 a_bogus 签名移植来源）

- 仓库：<https://github.com/Johnserf-Seed/f2>
- 版权 / 作者：JohnserfSeed（<https://github.com/johnserf-seed>）
- 许可证：Apache License 2.0（全文见 [Apache-2.0.txt](Apache-2.0.txt)）
- 涉及文件：`core/parsers/douyin/sign.py` —— 基于 `f2/utils/abogus.py`
  （原文件头含 `@Author: JohnserfSeed`、`@License: Apache License 2.0` 等归属信息）移植，
  **已修改**：移除 gmssl 依赖、内嵌纯 Python 的 SM3 实现、仅保留 `generate_abogus()`
  对外入口（改动说明见该文件头）。
