# Trade Helper V1 发布检查清单

## 自动门

- [ ] 全部自动测试通过；
- [ ] `git diff --check` 通过；
- [ ] `doctor` 无 `FAIL`；
- [ ] 备份、恢复并在新数据库运行 `doctor`；
- [ ] 影子运行达到至少20个交易日；
- [ ] 没有未解释的状态跳转；
- [ ] 历史回放无未来数据；
- [ ] 敏感性报告包含完整指标。

## Windows 客户端

- [ ] 干净 Windows 10 x64 启动；
- [ ] 干净 Windows 11 x64 启动；
- [ ] 账户表单和 Excel 原子导入；
- [ ] 重复 Excel 导入不重复记账；
- [ ] 数据阻断原因可见；
- [ ] 部分成交、完全成交、未操作和失败反馈；
- [ ] 关闭重启后状态保持；
- [ ] 高 DPI 与 125%/150% 缩放可用；
- [ ] 无控制台窗口；
- [ ] 未签名测试版有明确提示。
- [ ] 每日任务可以注册、手动运行并卸载；
- [ ] 休市日任务唤醒后安全跳过；
- [ ] 随包提供官方 2026 交易日历，缺日历任务自动补种；

## 数据安全

- [ ] 发布包不含 `var`；
- [ ] 发布包不含真实 Excel 或备份；
- [ ] `.gitignore` 忽略本地数据；
- [ ] 备份校验和破坏测试通过；
- [ ] 使用手册、隐私提示和风险提示随包提供。

## 人工评审门

- [ ] 冻结策略参数未被静默修改；
- [ ] 任何回测反证已有产品评审包；
- [ ] 当前真实持仓和现金已由用户核对；
- [ ] 用户确认仍采用人工下单；
- [ ] 发布版本号、变更说明和 Git 标签已准备。

## 自动门核验记录（2026-07-31）

依据 `release-readiness` 门禁、单元测试和仓库检查，使用 `var/acceptance/example.db`（示例账户）与 `data/replay/replay_suite.local.json`（四区间真实代理数据）复核：

- 全部自动测试通过：`python -m unittest discover -s tests` 123 通过、0 失败；
- `git diff --check` 通过（退出码 0）；
- `doctor` 无 FAIL（`ready: true`，示例库有 1 条 WARN：未完成建议）；
- 备份、恢复并在新数据库运行 `doctor` 通过（`backup_restore: true`）；
- 历史回放无未来数据：四个强制场景完整执行，输入哈希与转换记录见 `data/replay/*.audit.json` 与 `*raw.sources.json`，回放方法记录无前视；
- 敏感性指标完整：`data/replay/replay-suite.report.json` 每场景含收益、回撤、波动、换手和现金占用；跨参数变体敏感性证据报告已生成（`var/sensitivity/suite-sensitivity.json` 与 `SUMMARY.md`，基线 personal-v1 + 3 变体 × 4 区间，未修改冻结配置）；
- 影子运行：1/20 交易日，未达 20 日验收门，需真实交易日积累。

Windows 客户端、数据安全和人工评审门仍按上文清单等待干净机器验收、安装器验证与用户核对。

## 自动门核验记录补充（2026-07-31 下午）

- 每日流水线端到端验证：日历导入（5 行）→ 采集（过期补充文件+东财断连 → `ok:false` 阻断）→ 当日决策（交易日历缺失/时间窗口外 → `BLOCKED`，审计记录已入库）；休市/缺日历安全跳过行为符合文档；
- 打包 CLI 二进制 `dist/TradeHelperCLI.exe`：`doctor` 退出码 0；
- 发布包内容核验：不含 `var`、`data/replay`、真实 Excel 或备份；`.gitignore` 覆盖本地数据；
- GUI 打包核验：PyInstaller 归档含 `_tcl_data\init.tcl`、`tclIndex`、`tcl86t.dll`、`tk86t.dll` 及 921 项 Tcl/Tk 数据；沙箱内因路径虚拟化导致 Tcl 原生文件读取失败（`pwd` 显示路径缺 `Desktop\`），GUI 冒烟测试无法在沙箱内完成，需在沙箱外执行：
  `powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows_exe.ps1 -Executable .\dist\TradeHelper.exe -AllowVisibleLaunch`
- 安装器编译未执行：本机未安装 Inno Setup 6（`ISCC.exe` 不存在），需先安装后运行 `.\scripts\build_windows_installer.ps1 -Version 0.1.0`。
- 客户端“填写今日行情”表单已实现并测试（126 项测试通过）：数据中心内录入三标的报价/估值/指数/汇率/公告，保存并自动采集；旧 JSON 选择方式保留；
- 每日计划任务注册需在沙箱外执行：`.\scripts\register_daily_task.ps1 -CliExecutable .\dist\TradeHelperCLI.exe`（Codex 自动审核通道当前不可用，未代为注册）。
- 2026 交易日历：`data/calendar_2026.csv` 依据上证公告〔2025〕45号生成（365 天，元旦/春节/清明/劳动节/端午/中秋/国庆休市，无周末调休开市），来源见 `data/calendar_2026.source.md`；`calendar-import --if-missing-date` 仅当日历缺该日期时导入，`run_daily_pipeline.ps1` 每日自动补种；新增日历相关测试后全套 130 项通过。

## 运行安排更新（2026-08-03）

- 已按用户要求停止并注销 Windows 计划任务 `TradeHelper-DailyDecision`；当前没有后台每日流水线。
- 后续影子运行由当前 Codex 任务在用户明确要求时调用，不自动恢复 Windows 计划任务。
- 历史影子运行证据仍保留为 1/20；恢复真实影子运行前需先核对当前持仓、可用现金与当日行情。

## 本机构建与安装验收（2026-08-03）

- 修复浅色主题缺失的 `cyan_soft` 色值和发布说明中的异常换行；全套单元测试 131 项通过，`git diff --check` 通过。
- 使用 Python 3.12.13、PyInstaller 6.21.0 重建 GUI 与 CLI；GUI Tcl/Tk 8.6.12 探测通过。
- 新 GUI 可见冒烟通过：主窗口标题为 `Trade Helper · Personal V1` 且进程正常响应。
- 新 CLI `--help` 与示例数据库 `doctor` 通过；发布 ZIP 内容验证通过（20 项）。
- Inno Setup 6.7.3 编译成功；当前用户范围的首次安装、覆盖升级、卸载全部通过。
- 安装/卸载前后 `%LOCALAPPDATA%\TradeHelper\today-market.json` 哈希一致；用户数据保留通过。
- 当前 ZIP SHA-256：`4a30fd3b5604d4bf86be058b6cb3dd1513cbbe3ab0029f810bb2670a924b8c0a`。
- 当前安装器 SHA-256：`601ad73ce2233e69c170966faca2bdad7b8d382ee4b0f58ae060a02b4a0527cd`；测试版仍未签名。
- `release-readiness` 复核结果写入 `var/release-readiness-20260803.json`：doctor、历史回放、备份恢复通过；影子运行仍为 1/20，因此正式发布门未通过。

## 自动市场输入改造（2026-08-03）

- 用户确认产品原则：用户只记录真实成交、存取款和账户变化；市场输入不得要求用户每日填写或提供截图。
- 新浪、东方财富、腾讯提供三路自动 ETF 价格；东方财富 `f145` 与腾讯 ETF 参考值提供两路实时估值。
- 指数、汇率和人工公告在当前策略中未实际参与决策，已从 READY 强制入参中移除；关键自动源异常时仍安全阻断。
- 三只真实 ETF（513500、513100、515450）自动采集端到端验证全部 READY，未使用人工补充文件。
- 旧 `today-market.json` 默认不再被每日流水线拾取；只有开发者显式指定时才作为审计兜底输入。
- 真实账户快照已按用户确认写入本机本地数据库；内部现金池已自动对齐并建立写入前备份。验收文档和 Git 仓库不记录个人账户金额、券商信息或截图。
- 自动测试增至137项并全部通过。
