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
`TradeHelper.spec` 生成 `dist\TradeHelper.exe`。

当前产物是免安装单文件客户端。首次正式发布前还需要完成：

- Windows 10/11 干净虚拟机启动测试；
- Excel 导入、成交回填和备份恢复冒烟测试；
- 文件版本信息和应用图标；
- 代码签名或明确显示“未签名测试版”；
- 安装器与卸载流程。

不得把测试数据库、真实账户工作簿或 `var` 目录打入发布包。
