# Windows 构建与发布

## 构建环境

- Windows 10/11 x64；
- Python 3.11 或更高版本；
- 从项目根目录执行；
- 构建依赖通过 `pip install -e ".[build]"` 安装。

## 构建

```powershell
.\scripts\build_windows.ps1 -Python C:\path\to\python.exe
```

脚本先运行全部自动测试。测试失败时不会生成安装产物；测试通过后使用
`TradeHelper.spec` 生成 `dist\TradeHelper.exe`，随后生成
`TradeHelper-<version>-windows-x64.zip` 和对应 `.sha256`。发布包同时包含无控制台窗口的
`TradeHelper.exe` 客户端和用于回放、影子报告及发布验收的 `TradeHelperCLI.exe`。
如果同一发布阶段刚刚单独完成过全量测试，可显式传入 `-SkipTests`，避免重复执行；
不得用它跳过发布阶段的全量测试。

发布 ZIP 自动包含使用手册、隐私与风险提示、行情补充示例和账户模板。验证脚本检查
必需文件，并拒绝任何数据库、备份、`var` 内容或真实账户工作簿：

```powershell
.\scripts\verify_windows_release.ps1 -Archive .\dist\TradeHelper-0.1.0-windows-x64.zip
.\scripts\smoke_test_windows_exe.ps1 -Executable .\dist\TradeHelper.exe -AllowVisibleLaunch
```

GUI 烟雾脚本兼容 PyInstaller 单文件模式的父进程与 GUI 子进程，等待主窗口出现并确认
窗口可响应，然后正常关闭测试进程。构建脚本若发现 PyInstaller 因 Tcl/Tk 不可用而排除
`tkinter`，会直接失败，不会生成可发布结果。烟雾脚本默认拒绝运行，必须在提前告知用户
后显式传入 `-AllowVisibleLaunch`，避免客户端窗口突然出现。

安装器使用 Inno Setup 6 编译：

```powershell
.\scripts\build_windows_installer.ps1 -Version 0.1.0
```

用户已于 2026-07-30 明确允许后续下载并执行 Inno Setup 6；实际下载安装与编译留待
下一开发阶段执行并保留安装器哈希。

安装器采用每用户目录 `%LOCALAPPDATA%\Programs\TradeHelper`，默认不要求管理员权限。
卸载只移除程序文件和快捷方式，故意保留 `%LOCALAPPDATA%\TradeHelper` 中的个人数据库
及安全备份。安装前会展示未签名测试版说明，安装完成后的启动选项默认不勾选，避免
客户端突然出现。当前构建使用 Inno Setup 自带的英文安装器消息资源（用户文档和发布
说明仍为中文）。安装器同样生成独立 `.sha256` 文件。

发布流程同时支持免安装 ZIP 和每用户安装器。首次正式发布前还需要完成：

- Windows 10/11 干净虚拟机启动测试；
- Excel 导入、成交回填和备份恢复冒烟测试；
- 文件版本信息和应用图标；
- 代码签名或明确显示“未签名测试版”；
- 在干净虚拟机验证安装、升级、卸载及用户数据保留。

不得把测试数据库、真实账户工作簿或 `var` 目录打入发布包。

打包客户端默认将个人数据库保存在
`%LOCALAPPDATA%\TradeHelper\account.db`，不会尝试写入 EXE 所在目录。需要便携式
或自定义存储位置时，可在启动前设置 `TRADE_HELPER_DB`。
