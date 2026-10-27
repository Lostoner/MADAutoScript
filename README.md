# MADAutoScript

面向 **MAke Drama: MAD 国际服 ONEstore 版**的 Windows 日常自动化工具。使用 MuMu、ADB 截图与控制、BAAS OCR；执行框架来自 Blue Archive Auto Script，界面沿用 PyQt5 与 PyQt-Fluent-Widgets。

当前版本：**0.7.4**（首次公开发布候选）。目前实测环境为 Windows x64、MuMu 12、游戏简体中文、1920×1080 横屏。其他渠道、语言、模拟器与屏幕比例尚未验收。

## 已实现的功能

| 功能 | 当前能力 |
| --- | --- |
| 任务列表 | 开关、拖动排序、参数保存、停止、继续剩余计划、定时运行 |
| 体力领取 | 收取每日累积体力 |
| 普通扫荡 | 选择多个关卡，每关独立次数，按顺序执行 |
| 弗拉瑞区域、特别采购 | 共用学院交流形式的流程，分别选择分类、关卡和次数 |
| 普通商店 | 六种金币商品、独立数量；OCR 按商品名称定位，支持售罄后的重排 |
| 指定角色约会 | 选单指定角色、每日免费次数和地点优先级 |
| 邮箱、一键领取 | 邮箱、通行证、阿米商城免费物品、每日任务、积分宝箱、成就；子功能可选 |

竞技场、活动扫荡和特殊活动领取仍为待适配项。未完成真实连续跨两次日切的长时间验收。

已知限制：当前同一列表中的 MAX 关卡完成后，会结束该扫荡模块，后续关卡留待续跑。需要顺序处理多个关卡时，请将 MAX 放在最后或使用明确次数；此行为尚待修正。

## 使用 Windows 便携版

1. 下载 `MADAutoScript-0.7.4-windows-x64.zip`，完整解压到可写目录。不要在 ZIP 内直接运行。
2. 双击 `启动MADAutoScript.cmd`。便携版已包含 Python、Qt、OCR，无需另装 Python。
3. 在「设置」中选择 MuMu 的 `mumu-cli.exe`，填写实例编号。ADB 路径通常可留空；若未找到，选择同一 MuMu 安装目录中的 `adb.exe`。
4. 启动该实例中的 ONEstore MAD，登录并停在游戏主页。设置游戏语言为简体中文、分辨率为 1920×1080。
5. 勾选所需任务，展开卡片配置关卡、次数和商品，调整顺序后「保存并开始」。

次数 **0 表示 MAX**，由游戏原生控件决定可执行数量。资源用尽、库存售罄属于正常结果；不会主动购买或补充体力，也没有额外的累计消费上限。购买任务按你保存的商品和数量消耗金币。

「开始 / 继续」保留剩余关卡；「… → 开始新一轮」才重建完整计划。运行时避免同时手动操作同一个 MuMu。

## 从源码运行

需要 Windows x64、**Python 3.11** 和 Git。源码 ZIP 不包含运行时。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock.txt
.\.venv\Scripts\python.exe scripts\install_ocr.py
.\启动MADAutoScript.cmd
```

安装脚本固定 OCR 提交并校验每个文件的 SHA-256。日常启动不会自动下载或更新依赖。已有 OCR 可执行 `python scripts/install_ocr.py --verify-only` 离线核对。

本项目按目录运行；请保留 `src/`、`docs/ocr-runtime.lock.json` 和 `runtime/ocr/` 的相对位置，不使用 `pip install .` 代替上述安装步骤。

## 配置、升级和日志

首次打开自动生成 `config/`，不会携带发布者的设备路径、账号配置或任务进度。`config/default/config.json` 保存参数与剩余关卡，`event.json` 保存任务顺序和调度；`config/app.json` 保存主题。

升级时关闭旧程序，将新版本解压到新目录，再复制旧版 `config/` 和 `state/`。不要用旧备份覆盖已经更新的进度。原目录可保留用于回退。

运行记录在 `runs/`，启动错误在 `state/startup-error.log`。反馈问题时可附日志和必要的局部截图，请先去除账号信息；不要上传整个 `config/` 或 `runs/`。

## 隐私与公开范围

配置、任务进度、日志和截图保存在程序本地目录。截图和 OCR 结果可能包含游戏昵称、UID、资源数量等账号信息；分享前请逐项检查。MADAutoScript 不要求填写游戏密码，登录由游戏客户端完成；截图 OCR 使用本机服务。

发布包只带代码、游戏选单数据和 34 张局部界面识别图，不带开发者的账号配置、设备路径、实机日志、完整截图或 Git 历史。关卡目录与识别图的本机采集路径在导出时移除。第三方源码中的原始版权声明和上游测试资料保持原样。

## 参与贡献

欢迎提交代码、报告可复现的问题、协助测试或改进文档。先阅读 [贡献指南](CONTRIBUTING.md)，也可以从 [4 个新手待办](docs/STARTER_TASKS.md) 中认领一项。测试和文档贡献同样重要。

仓库公开后，Bug 使用 [问题模板](.github/ISSUE_TEMPLATE/bug_report.md)，建议使用 [改进模板](.github/ISSUE_TEMPLATE/feature_request.md)；代码和文档修改通过 Fork → 分支 → PR 提交，按 [PR 模板](.github/pull_request_template.md) 说明改动和实际验证结果。日志、截图分享前请脱敏。当前待办尚未创建为 GitHub Issue。

## 开发与发布

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

公开源码中的测试使用临时配置，不依赖开发者备份，也不连接游戏。历史实机验收结论见 [当前工作状态](docs/STATUS.md)。构建和上传步骤见 [发布说明](docs/RELEASING.md)，本次变更见 [CHANGELOG](CHANGELOG.md)。

## 来源与许可

应用源码采用 **GPL-3.0-only**，完整条款见 [LICENSE](LICENSE)。本项目是 [BAAS](https://github.com/pur1fying/blue_archive_auto_script) 的派生项目，基线为 `1110e88df5955df277737ea9717869b9ca88362b`，保留 pur1fying 及原贡献者的归属。修改范围和日期见 [UPSTREAM.txt](UPSTREAM.txt)、[CHANGELOG](CHANGELOG.md)；公开包中的 `docs/source-manifest.json` 记录实际文件与哈希。

| 项目 | 与当前版本的实际关系 |
| --- | --- |
| BAAS / BAAS C++ OCR | 应用代码上游 / 实际 OCR 运行依赖，均保留适用 GPL 声明 |
| [MaaBd2](https://github.com/alkaidjin/Maa-Assistant-Browndust2)（Maa-Assistant-Browndust2） | 任务卡片、布局与字体选择的设计参考；未引入其代码、程序、字体文件或图片资源 |
| [MaaFramework](https://github.com/MaaXYZ/MaaFramework) | 曾评估的候选框架；当前版本未使用、未打包，迁移暂缓 |

感谢上述项目及 Python、Qt、PyQt、Fluent Widgets、OpenCV、PaddleOCR、ONNX Runtime 等项目的作者和贡献者。详细关系与致谢见 [NOTICE](NOTICE.md)，实际依赖、许可证和源码位置见 [THIRD_PARTY.txt](THIRD_PARTY.txt)。参考关系不表示上游参与、审核或背书，也不把未使用项目的许可证合并为本项目许可。

再分发时保留适用的作者归属、许可证和修改说明；便携 ZIP 应与该版本源码 ZIP、`third-party-sources.zip` 一同提供，并保留源码内的构建步骤。项目没有增加“禁止商用”等限制 GPL 权利的条款，各第三方组件及游戏素材继续适用各自的条款。

游戏名称与用于界面识别的局部 UI 图片归各自权利人所有，不属于本项目 GPL 授权的原创美术。此项目不是游戏官方产品，不包含游戏客户端、账号或完整美术素材。

当前维护重点是玩家反馈、现有日常功能和安装体验。暂不推进 MaaFramework 迁移；新增玩法按 MAD 实际需求设计，不要求先在 BAAS 找到对应任务。
