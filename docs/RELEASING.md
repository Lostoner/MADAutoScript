# 构建与发布

## 构建

在 Windows x64、已按 README 安装依赖和 OCR 的源码目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\vendor_sources.py
.\.venv\Scripts\python.exe scripts\build_release.py --output dist\v0.7.4
```

构建器以入口的实际导入关系挑选 MAD 代码，排除只供类型检查的 BAAS 旧运行时；资源和维护脚本采用显式清单。不会拷贝开发目录的 `.git`、配置、进度、日志、截图、备份或其他游戏。

导出时仅保留关卡目录中的游戏数据，移除采集证据路径；识别图来源仅保留内容哈希。构建器检查源码和便携目录中的当前工作区、用户目录路径，包含原始及解析后路径、JSON 转义、文件 URI 与二进制字符串，并排除运行时的本地安装来源和常见凭据文件。该检查不能代替对新增文件和图片的人工复核，公开范围见 [README](../README.md#隐私与公开范围)。

默认复制当前解释器的完整 Python 基础目录和当前环境的依赖，适用于独立 Windows Python 3.11 分发。可用 `--python-runtime` 和 `--site-packages` 显式指定。不会把含绝对路径的虚拟环境直接当成便携运行时。

`vendor_sources.py` 下载 Qt 5.15.2、PyQt5 5.15.11 与固定提交的 BAAS C++ 源码；未改动的 Python 依赖源码和许可证随便携运行时保留。源码归档地址、版本和哈希记录在第三方源码包的 `SOURCES.json`。

`licenses/` 保存上游 wheel 缺失的许可文本及 ONNX Runtime 第三方声明，来源和哈希记录在其 `SOURCES.json`。构建器核对这些哈希，并检查每个实际 Python 发行包有原始许可文件或补充文本。不要把重新下载的另一版本源码当成现有二进制的对应源码。

## 输出

- `source/MADAutoScript/`：可直接作为新 GitHub 仓库根目录。
- `MADAutoScript-0.7.4-source.zip`：同一份应用源码快照。
- `MADAutoScript-0.7.4-windows-x64.zip`：含 Python、依赖和 OCR 的便携版。
- `MADAutoScript-0.7.4-third-party-sources.zip`：随二进制分发的对应第三方源码。
- `SHA256SUMS.txt`：上述归档的校验和。

产物目录必须是新目录，避免把旧发布内容混入新版本。应用源码公开包不包含 Python/Qt/OCR 二进制。

## 必要的发布前核对

- 核对 README、NOTICE、UPSTREAM、THIRD_PARTY 与实际应用和运行时一致；保留 GPL 原文及作者归属。当前包不使用 MaaFramework，MaaBd2 仅为设计参考。
- 三个 ZIP 能完整读取，SHA-256 与清单一致；源码 ZIP 与便携包中的应用文件一致，源码及第三方源码对应本次二进制。
- 确认贡献资料和许可文本随包，链接可解析；构建输出不含个人配置、进度、日志、截图、凭据或开发目录路径。
- 仅改文档和打包时，比较应用、运行时和识别图片的哈希，复用未变部分的有效验证；有功能改动才补相关测试。不得把既有实机证据写成本轮重新验证。
- 已知限制及未验证环境写入 README / STATUS；本地验收记录保留实际完成与未完成事项，不宣称完成法律审查。

## 发布到 GitHub

1. 将 `source/MADAutoScript/` 的内容上传到为本项目新建的仓库，包括隐藏的 `.github/` 目录；不要把整个开发工作区或原有上游历史仓库推送过去。
2. 以 `v0.7.4` 创建 Release，采用 `CHANGELOG.md` 中该版本的说明。
3. 同时上传三个 ZIP 和 `SHA256SUMS.txt`，让便携版与对应源码在同一个 Release 可下载。
4. 下载发布产物，按校验和验证完整性。Windows 用户下载 `windows-x64.zip`；源码与第三方源码供开发、审计及再分发使用。

贡献指南、Issue 与 PR 模板已随源码打包；模板进入仓库默认分支后才会用于新建问题和 PR。首次公开后，可将 [新手待办](STARTER_TASKS.md) 的 4 项分别创建为 Issue、添加文中建议标签并在待办表补上链接；目前没有创建任何远程 Issue，也没有虚构认领者。

本地打包不会创建远程仓库、推送提交或发布 Release。自动检查工作流只执行离线测试，不会自动发布。
