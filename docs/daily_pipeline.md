# 每日生产流水线

Windows 计划任务在工作日 14:40 启动，但最终是否运行策略仍由数据库中的显式
A 股交易日历判断。流水线依次执行：

1. 检查当日人工补充行情 JSON 是否存在且格式有效；
2. 采集新浪、东方财富及补充文件中的独立券商/估值/指数/汇率/公告数据；
3. 仅在三个标的行情快照全部 READY 时进入当日决策；
4. 决策服务再次检查交易日、14:00–14:50 时间窗、账户对账和持久化状态。

准备文件：

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\TradeHelper"
Copy-Item .\config\market_supplement.example.json `
  "$env:LOCALAPPDATA\TradeHelper\today-market.json"
```

每个交易日必须更新 `observed_at` 和实际来源值，不能直接复用示例值。注册任务：

```powershell
.\scripts\register_daily_task.ps1
```

手工演练完整流水线：

```powershell
.\scripts\run_daily_pipeline.ps1
```

如果补充文件缺失、字段无效、任一标的未达到 READY 或决策检查失败，脚本返回非零
状态且不会生成可执行建议。公共源临时失败但独立券商报价成功补位时，采集输出会显示
`ok: true` 与 `degraded: true`，并保留失败源审计记录。
