# Trade Helper

Windows 本地低频 ETF 仓位管理助手。项目已完成数据可行性探针和账户数据底座的首批实现；不连接券商、不自动下单。

## MVP 目标

- 在 A 股交易日 14:00 左右取得 513500、513100、515450 的公开行情；
- 检查最新价、IOPV、时间戳和数据新鲜度；
- 明确区分“数据可用于提醒”和“数据足以生成可执行建议”；
- 在下单前展示原始数据、来源差异、决策建议和状态机，供用户复核；
- 输出机器可读的 JSON 报告，为后续仓位策略保留稳定接口。

免费公开源不作交易所级实时行情承诺。QDII ETF 只有一个估值源时，程序必须要求人工在券商客户端复核。

## 本地运行

需要 Python 3.11 或更高版本。

```powershell
python -m trade_helper.cli probe --output .\var\feasibility.json
python -m unittest discover -s tests -v
```

Excel 导入采用“预览后提交”流程。预览只校验、不写数据库：

```powershell
python -m trade_helper.cli excel-preview .\outputs\account_template\trade_helper_account_template.xlsx
python -m trade_helper.cli excel-import .\outputs\account_template\trade_helper_account_template.xlsx --database .\var\account.db
```

导入以整个文件为事务边界：任一有效数据行错误都会阻止整批写入；同一内容重复
导入会返回 `"imported": false`，不会重复生成快照、成交或资金流水。模板自带示例行，
正式使用时应删除或覆盖示例数据。

启动 Windows 客户端界面：

```powershell
python -m trade_helper.ui.app
```

创建经过 SQLite 完整性检查和 SHA-256 校验的本地备份：

```powershell
python -m trade_helper.cli backup --database .\var\account.db --output .\var\backups\account.thbackup
python -m trade_helper.cli restore .\var\backups\account.thbackup --database .\var\account-restored.db
```

恢复操作会先在临时目录校验归档结构、文件大小、内容哈希和 SQLite 完整性，全部
通过后才替换目标数据库。

汇总影子运行覆盖情况（默认验收门为20个有审计记录的交易日）：

```powershell
python -m trade_helper.cli shadow-report --database .\var\account.db --output .\var\shadow-report.json
```

也可以使用 Windows 脚本，并在未配置 PATH 时传入 Python 完整路径：

```powershell
.\scripts\run_probe.ps1 -Python C:\path\to\python.exe
.\scripts\run_tests.ps1 -Python C:\path\to\python.exe
```

源代码采用 `src` 布局；在未安装包时，可在 PowerShell 中临时设置：

```powershell
$env:PYTHONPATH = "$PWD\src"
```

## 当前边界

- 不保存券商账号、密码或个人身份信息；
- 不抓取或模拟操作券商客户端；
- 不生成自动委托；
- 外部数据异常时输出 `BLOCKED`，不猜测价格。

## 已实现的基础能力

- 东方财富与新浪公开行情探针；
- 三资产个人策略配置及启动校验；
- 本地 SQLite 账户快照、持仓、交易和资金流水存储；
- 不含佣金和税费的 Excel 人工维护模板；
- 自动化单元测试。

个人策略草案位于 `config/personal_v1.json`。其中比例、资金池和风控约束均可配置，
但在黄金场景通过用户确认前保持 `DRAFT` 状态。

账户数据遵循以下原则：

- 券商持仓与资金由用户通过应用录入或 Excel 导入；
- 行情、指数、汇率和基金公开信息优先自动采集；
- 券商专有实时 IOPV 无稳定公开接口时，允许盘中人工补录；
- 金额在本地数据库中使用“分”保存，ETF 价格使用千分之一元保存，避免浮点误差；
- 第一阶段只输出建议单，不连接券商自动下单。
- 用户账户只纳入三只指定权益ETF和一只货币基金；货币基金全部计入现金。
- 基础建仓池、回撤池和战略现金由系统内部维护，用户无需手工拆分。
