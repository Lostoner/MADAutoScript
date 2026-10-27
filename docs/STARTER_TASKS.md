# 新手待办

以下 4 项均为待认领的本地草案，尚未创建 GitHub Issue。仓库公开后，维护者可按各项标题创建 Issue 并添加建议标签；参与者在对应 Issue 下留言认领即可。测试和文档贡献同样欢迎，暂时不能继续时留言交接即可。

| 编号 | 任务 | 类型 | 当前状态 |
| --- | --- | --- | --- |
| GF-01 | 在另一台 Windows 电脑验证便携版安装 | 测试、文档 | 待认领 |
| GF-02 | 补充三张脱敏的入门界面截图 | 文档 | 待认领 |
| GF-03 | 编写“继续剩余计划与开始新一轮”FAQ | 文档 | 待认领 |
| GF-04 | 为次数和数量控件补充可访问名称 | 小型 UI 修改 | 待认领 |

## GF-01：在另一台 Windows 电脑验证便携版安装

建议标签：`good first issue`、`help wanted`。

目标：补充当前尚缺的另一台物理电脑上的安装证据。按 [README](../README.md) 在 Windows x64 的新目录解压启动，检查新配置、任务选单和设置页；不点击“开始”，不运行游戏日常。

可以运行已有的离线检查（在便携目录下）：

```powershell
.\runtime\python\python.exe scripts\check_install.py --ocr
```

该检查用临时配置打开 Qt 窗口、加载模板并识别生成的文字，不连接模拟器或操作游戏。输出含本机路径，分享前请脱敏。

相关文件：[安装检查脚本](../scripts/check_install.py)、[当前状态](STATUS.md)。提交内容为环境信息、操作结果，以及 README 中确实需要补充的安装说明；成功或失败报告都可提交。

验收：记录软件版本、Windows 版本/架构、新目录启动结果、Qt/模板/OCR 结果；若失败附脱敏错误和发生步骤。仅成功结果可用于更新“尚未异机验证”的说明，不把失败测试标为通过。

## GF-02：补充三张脱敏的入门界面截图

建议标签：`good first issue`、`documentation`。

目标：给 [README](../README.md) 增加任务列表、添加关卡选单、设备设置三张图片，让首次使用者容易找到入口。

参考 [check_install.py](../scripts/check_install.py) 中 `create_window(临时目录)` 的做法，用空白临时配置打开 UI；可以编辑演示参数，不开始任务。图片放在 `docs/images/`，使用相对路径引用，写简短图注和替代文本。

验收：三张图中文字清楚、与当前 UI 一致；没有账号、真实设备路径、日志、桌面其他窗口或截图元数据；README 中正常显示。将新增图片加入 [发布清单](../scripts/build_release.py) 的 `PUBLIC`，让源码包也能显示图片。无需改 UI 或运行游戏。

## GF-03：编写“继续剩余计划与开始新一轮”FAQ

建议标签：`good first issue`、`documentation`。

目标：解释“开始 / 继续”“开始新一轮”“保存配置”分别如何影响剩余关卡，用一个两关计划的例子说明第一关已完成后继续执行什么。

相关文件：[工作台](../gui/fragments/routine.py)、[配置与进度](../core/config/repository.py)、[现有进度测试](../tests/test_release_core.py)。阅读现有实现和测试即可；不需要为写文档重复消耗游戏体力。

提交内容：新增 `docs/FAQ.md`，在 README 增加入口，并将文档加入 [发布清单](../scripts/build_release.py)。

验收：术语与实际按钮一致，准确区分配置计划和本轮剩余计划；例子不暗示保存会重置进度；所有相对链接有效。

## GF-04：为次数和数量控件补充可访问名称

建议标签：`good first issue`、`enhancement`。

目标：让辅助工具能区分不同关卡、商品及约会的数字输入框。目前这些数量控件没有各自的 `accessibleName`，同页其他操作按钮已有相关做法。

相关文件：[gui/fragments/routine.py](../gui/fragments/routine.py) 中 `SweepSelector` 的次数控件、普通商店数量控件、`dating_count`；可参考同文件已有的 `setAccessibleName()`。

改动范围：只补能辨认对象的名称，例如“当前关卡标题＋扫荡次数”“商品名称＋购买数量”“约会次数”；保留控件取值、MAX 含义、配置键、顺序和布局。

验收：用临时配置确认多行控件名称不为空且能区分对象，重新渲染后仍正确；按需在现有 UI 测试中补相关断言。无需连接模拟器或添加新测试框架。
