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
`TradeHelper-<version>-windows-x64.zip` 和对应 `.sha256`。

发布 ZIP 自动包含使用手册、隐私与风险提示、行情补充示例和账户模板。验证脚本检查
必需文件，并拒绝任何数据库、备份、`var` 内容或真实账户工作簿：

```powershell
.\scripts\verify_windows_release.ps1 -Archive .\dist\TradeHelper-0.1.0-windows-x64.zip
```

安装器使用 Inno Setup 6 编译：

```powershell
.\scripts\build_windows_installer.ps1 -Version 0.1.0
```

安装器采用每用户目录 `%LOCALAPPDATA%\Programs\TradeHelper`，默认不要求管理员权限。
卸载只移除程序文件和快捷方式，故意保留 `%LOCALAPPDATA%\TradeHelper` 中的个人数据库
及安全备份。安装器同样生成独立 `.sha256` 文件。

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
