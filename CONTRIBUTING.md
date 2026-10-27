# 参与 MADAutoScript

欢迎提交代码、复现问题、协助测试和改进文档。第一次参与可以从 [4 个新手待办](docs/STARTER_TASKS.md) 中选一项；它们目前是本地待办草案，仓库公开后可在对应 Issue 下认领。

## 提交一个小改动

1. 按 [README](README.md) 安装开发环境，从源码启动。使用独立工作目录，不要拿日常使用目录直接试验。
2. 仓库公开后，Fork 到自己的账号，新建分支修改；小修复可直接提交 PR，大功能、配置格式或框架变更先开 Issue 说明操作流程。
3. 一次 PR 解决一个问题，填写修改原因、验证结果和关联 Issue；没有实机验证的部分如实标明。
4. 根据评审调整，维护者负责合并和发布。认领后暂时没空，留言即可；请尊重不同经验的参与者，讨论具体问题。

当前范围为 ONEstore 国际服、MuMu、简体中文和已验证分辨率。活动特殊页面、竞技场与新渠道先明确规则，再安排实现；已有边界见 [当前状态](docs/STATUS.md)。

## 从哪里读代码

| 要做什么 | 入口 |
| --- | --- |
| 理解执行与调度 | [core/Mad_thread.py](core/Mad_thread.py)、[core/scheduler.py](core/scheduler.py) |
| 修改一项游戏功能 | [module/mail.py](module/mail.py) 等 `module/` 中的对应文件 |
| 修改页面识别与入口 | [core/mad_features.py](core/mad_features.py)、[module/restart.py](module/restart.py) |
| 注册任务、子功能与默认参数 | [core/tasks.py](core/tasks.py)、[core/routine_catalog.py](core/routine_catalog.py) |
| 修改选单、数量或界面文案 | [gui/fragments/routine.py](gui/fragments/routine.py)、[core/game_catalog.py](core/game_catalog.py) |
| 处理配置兼容与剩余计划 | [core/config/repository.py](core/config/repository.py) |

例如，接入一项已确定规则的领取子功能：参考 `module/mail.py` 编写 `implement(self)`；在 `core/mad_features.py` 补所需页面识别和入口；在 `module/claim_all.py` 注册处理函数，在 `core/tasks.py` 的 `CLAIM_MODULES` 及 `core/routine_catalog.py` 中补选项和默认值。先单独验证该子功能，再验证勾选后能被一键领取调用；无需为此再建一套调度框架。

当前维护 BAAS 派生执行结构，MaaFramework 迁移暂缓；新玩法按 MAD 的实际需求实现，不要求先在 BAAS 找到对应任务。保留已有配置、用户顺序和剩余进度；不要顺手重构无关功能。识别图片只提交必要的局部 UI，并保留来源和版权说明。

## 做与改动相称的验证

- 文档和模板：检查步骤、链接及格式，无需运行游戏。
- UI：验证所改控件的显示与交互，可参考 [工作台测试](tests/test_ui_workspace.py)，无需执行真实购买或扫荡。
- 配置和调度：验证相关保存、恢复或执行顺序，可参考 [配置与进度测试](tests/test_release_core.py)。
- 游戏流程：说明版本、起止页面、是否成功及实际资源消耗；离线识别通过不能写成实机跑通。只操作自己有权测试的账号和设备。

离线测试按修改范围选用，例如界面修改：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ui_workspace.py -v
```

需要完整离线检查时，去掉 `-p test_ui_workspace.py`。已有结果仍有效时不必反复跑。AI 辅助修改也需要提交者理解代码，并说明真实验证结果。

## 反馈与隐私

Bug 请使用问题模板，提供最短复现步骤；建议请说明想解决的场景。日志、图片先遮挡昵称、UID、本机用户名及凭据，不上传整个配置或运行目录。涉及凭据泄漏时先撤销凭据，不在公开 Issue 中贴出秘密内容；更多说明见 [隐私检查](docs/PRIVACY.md)。

提交前检查 Git 作者名和邮箱是否适合公开。应用代码贡献按项目 GPL-3.0-only 条款提交，贡献者保留其版权；不要求版权转让或另签 CLA。只提交自己有权授权的内容，保留上游作者归属及原文件声明。

新增第三方代码或资源时，注明原项目、具体版本或提交、使用文件、修改内容及许可证，更新 [NOTICE](NOTICE.md) 和 [THIRD_PARTY.txt](THIRD_PARTY.txt)；根据实际组合方式核对许可后再合并。仅参考交互思想时如实标注参考，不虚列成运行依赖。维护者会在发布说明中记录贡献，项目不承诺即时答复或接受所有功能建议。
