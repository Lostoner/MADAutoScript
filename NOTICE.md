# 来源、修改与致谢

适用版本：MADAutoScript 0.7.5；更新日期：2026-10-28。应用源码采用 [GPL-3.0-only](LICENSE)。本文件记录实际来源及感谢对象，不替代各组件的完整许可条款。

## 应用代码与执行能力

**Blue Archive Auto Script（BAAS）** — 感谢 pur1fying 和 BAAS 贡献者。

- 上游：[pur1fying/blue_archive_auto_script](https://github.com/pur1fying/blue_archive_auto_script)。
- 基线：[`1110e88df5955df277737ea9717869b9ca88362b`](https://github.com/pur1fying/blue_archive_auto_script/tree/1110e88df5955df277737ea9717869b9ca88362b)。
- 许可：[上游 GPLv3](https://github.com/pur1fying/blue_archive_auto_script/blob/1110e88df5955df277737ea9717869b9ca88362b/LICENSE)，本项目保留其完整文本与现有文件内的作者、来源声明。
- 使用范围：应用生命周期、任务组织与调度、页面识别及恢复、设备与 OCR 接口、配置和部分 Qt 控件。MADAutoScript 是其派生项目，不声明这些部分为从零独立创作。

MADAutoScript 贡献者自 2026-10-22 起加入 MAD ONEstore 的页面识别、任务和关卡数据、配置与进度适配、商店 OCR 商品定位、Qt 工作台以及独立打包流程。具体版本变更见 [CHANGELOG](CHANGELOG.md)，来源概述见 [UPSTREAM.txt](UPSTREAM.txt)。保留原作者归属不要求新玩法照搬 BAAS；后续功能按 MAD 实际需求维护。

**BAAS C++ OCR** — 感谢 pur1fying 和 BAAS_Cpp 贡献者。

- 实际使用本地 OCR 服务；其许可为 GPLv3。
- 固定源码：[`4c276b1d514ecf2f9025be7d549cdbc31e6218f7`](https://github.com/pur1fying/BAAS_Cpp/tree/4c276b1d514ecf2f9025be7d549cdbc31e6218f7)。
- 预构建版本、来源、模型和文件哈希见 [ocr-runtime.lock.json](docs/ocr-runtime.lock.json)。对应上游源码随同版本第三方源码 ZIP 提供。

## 界面参考及暂未使用的项目

**MaaBd2（Maa-Assistant-Browndust2）** — 感谢 [alkaidjin/Maa-Assistant-Browndust2](https://github.com/alkaidjin/Maa-Assistant-Browndust2) 及贡献者。参考包为 v26.10.8，参考内容为任务卡片、参数展开、状态布局与字体观感。当前 MAD 界面使用原有 PyQt5/Fluent Widgets 技术栈实现，未引入 MaaBd2 或其 MXU 前端的源码、可执行文件、字体或图片。本项为设计参考致谢，不是运行依赖，也不据此将其 AGPLv3 声明为本应用许可证。

**MaaFramework** — 感谢 [MaaXYZ/MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的公开文档，曾用于评估后续执行框架方案。0.7.5 未调用或分发 MaaFramework，不应标注为“Powered by MaaFramework”。迁移现已暂缓；本发布继续维护现有 BAAS 派生执行链。

如以后实际引入这些项目的实现，需在引入时记录具体文件、版本与适用许可，更新依赖和分发资料；当前致谢不构成未来使用的额外授权。

## 实际依赖及其他权利人

感谢 Python Software Foundation 与 CPython 贡献者、The Qt Company 与 Qt 贡献者、Riverbank Computing、zhiyiYo 与 Fluent Widgets/Frameless Window 贡献者，以及 NumPy、OpenCV、PaddleOCR、Microsoft ONNX Runtime、adbutils、Requests 和各间接依赖的维护者。实际版本和随包许可位置见 [THIRD_PARTY.txt](THIRD_PARTY.txt)。上游文件中的原版权、专利、商标及第三方声明继续保留。

游戏名称、角色名、界面及 34 张功能识别裁剪归游戏原权利人所有；本项目的 GPL 不授予这些素材的版权。识别图来源在 `src/images/MAD_onestore_zh-CN/provenance.json` 中记录。Segoe UI / Microsoft YaHei UI 使用 Windows 系统字体，不随包分发字体文件。MuMu、游戏客户端和其账号服务均由用户另行安装、使用，不包含在发布包中。

本项目由 MADAutoScript 维护者单独维护，不是 BAAS、MaaBd2、MaaFramework、MuMu 或游戏官方项目；致谢不表示任何上游参与维护、审核或背书。

## 分发说明

修改及再分发应用时遵循 GPLv3，保留适用声明并说明修改；二进制对应源码和构建资料须按许可提供。第三方组件继续采用各自许可，不统一改成 GPL、LGPL、AGPL 三选一。原许可证中的无担保条款保持有效；本文件不增加禁止商用、禁止修改或禁止再分发等限制。

公开 Release 应同时提供应用源码 ZIP、Windows 便携 ZIP、第三方对应源码 ZIP 和校验和；具体步骤见 [RELEASING](docs/RELEASING.md)。
