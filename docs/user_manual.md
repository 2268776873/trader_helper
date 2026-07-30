# Trade Helper V1 使用手册

## 1. 产品边界

Trade Helper 是 Windows 本地低频 ETF 仓位管理助手。它只生成可复核的建议，
不连接券商、不保存券商账号密码、不自动下单，也不承诺收益。

第一版账户只维护：

- 513500 标普500；
- 513100 纳指100；
- 515450 红利低波；
- 一只用户选择的货币基金或现金余额。

## 2. 首次初始化

1. 保留 `config/personal_v1.json`，不要直接修改已激活版本。
2. 准备账户 Excel，删除或覆盖模板示例行。
3. 启动客户端：

   ```powershell
   python -m trade_helper.ui.app
   ```

4. 点击“导入账户 Excel”，先查看预览，再确认原子写入；也可点击“录入账户”
   直接填写三只 ETF 的份额、市值、账户总资产和现金。
5. 账户必须满足：现金加三项持仓市值等于总资产。否则进入待对账状态。
6. 导入显式 A 股交易日历，不允许软件用周一至周五猜测开市。

可选：注册每日14:00 Windows任务。注册脚本只负责工作日唤醒，程序仍以显式
交易日历判断是否开市：

```powershell
.\scripts\register_daily_task.ps1
```

移除任务：

```powershell
.\scripts\unregister_daily_task.ps1
```

## 3. 每日流程

### 14:00 前

1. 核对券商账户的总资产、三项持仓和现金。
2. 补录当日存取款和例外交易。
3. 准备人工复核数据：券商盘口、双估值、指数、汇率、公告状态和人民币参考价值。

### 14:00 至 14:50

1. 运行市场采集：

   ```powershell
   python -m trade_helper.cli market-collect .\var\today-market.json --database .\var\account.db
   ```

2. 运行每日决策：

   ```powershell
   .\scripts\run_daily_decision.ps1 -Python C:\path\to\python.exe
   ```

3. 在客户端核对原始数据、来源时间、权重、回撤、溢价、资金池、数量与限价。
4. 若状态为 `BLOCKED` 或 `RECONCILIATION_REQUIRED`，不得绕过程序追价。
5. 用户在券商客户端自行下限价单。

### 下单后

- 没有下单：点击“未操作”；
- 已提交但未成交：点击“已下单”；
- 有实际成交：点击“回填成交”，填写实际数量和价格；
- 部分成交可多次回填，但累计份额不能超过建议份额；
- 撤单、拒单和过期只改变审计状态，不改变持仓和现金；
- 只有实际成交写入真实交易账本。

## 4. 常见阻断

| 状态或原因 | 处理 |
|---|---|
| 账户不平衡 | 重新核对现金和三项持仓市值 |
| 缺少交易日历 | 导入包含当日的正式日历数据 |
| 单一行情源失败 | 等待恢复或保留阻断快照，不猜价格 |
| 双估值缺失/冲突 | 在券商或独立来源复核后重新采集 |
| 行情超过5分钟 | 重新采集 |
| 公告或停牌风险 | 确认风险解除前不交易 |
| 现金低于5万元 | 暂停新增买入 |
| 取款超过现金 | 进入人工策略评审，不自动卖权益 ETF |

## 5. 历史与影子运行

- 点击侧边栏“历史审计”查看决策、成交和资金流水时间线。
- 运行 `shadow-report` 查看“20日覆盖”和“验收通过”两个状态。达到天数但仍有
  未处置建议、重复成功决策或交易日历异常时，不会通过验收。
- 影子运行阶段只生成建议，不依赖程序执行真实订单。
- 回放报告必须同时检查收益、最大回撤、波动、换手和现金占用。

## 6. 备份与恢复

建议每次账户导入、配置切换和实际成交回填后创建备份：

```powershell
.\TradeHelperCLI.exe backup --database .\var\account.db --output .\var\backups\account.thbackup
```

恢复前先关闭客户端。建议优先恢复到新的数据库路径验证：

```powershell
.\TradeHelperCLI.exe restore .\var\backups\account.thbackup --database .\var\restored.db
.\TradeHelperCLI.exe doctor --database .\var\restored.db --config .\config\personal_v1.json
```

## 7. 发布前验收

`release-readiness` 会在不启动客户端的情况下统一检查：

- 数据库、冻结配置和运行状态；
- 影子运行的覆盖天数与审计完整性；
- 四个强制历史压力区间；
- 临时目录中的备份、恢复和恢复后数据库诊断。

自动门禁通过不等于正式发布完成。报告会继续列出干净 Windows 10/11、125%/150%
DPI、真实账户核对、未签名提示与人工下单政策等人工门禁。

备份包含本地账户数据库，必须按个人财务数据妥善保管。

## 8. 故障自检

```powershell
.\TradeHelperCLI.exe doctor --database .\var\account.db --config .\config\personal_v1.json
python -m unittest discover -s tests
```

出现未解释的状态跳转、重复建议、现金突破底线或回放反证时，不要修改冻结配置；
先保存数据库备份、相关输入、错误输出和复现步骤，形成产品评审包。
