# 策略历史回放

`strategy-replay` 会逐交易日调用当前冻结策略，而不是对预先生成的资产曲线做事后统计。每一天只能读取当天及以前的数据；回撤高点使用最多 250 个已读取交易日。

输入 CSV 必须按日期严格递增且不重复，包含：

- `trading_date`
- 每个资产（`SP500`、`NASDAQ`、`DIVIDEND`）的
  `<ASSET>_price`、`<ASSET>_nav_1`、`<ASSET>_nav_2`、
  `<ASSET>_reference`

其中 `price` 是可执行价格，两项 `nav` 用于溢价与数据一致性检查，
`reference` 是回撤参考序列。所有数值必须为有限正数。

运行示例：

```powershell
python -m trade_helper.cli strategy-replay .\data\history.csv `
  --initial-account .\config\replay_initial_account.example.json `
  --output .\var\strategy-replay.json `
  --trajectory .\var\strategy-replay-trajectory.csv
```

当前回放执行代理为“建议在同一行提供的可执行价格全部成交”，不包含手续费。
卖出净额按已确认的方案 A 全部进入战略现金。报告会明确记录这些假设，因此不能把
结果解释为真实券商逐笔成交复现。

2000 年互联网泡沫、2008 年金融危机、2022 年下跌和长期上涨区间必须使用可审计的
真实历史输入分别运行。仓库中的示例初始账户不是历史行情，也不能替代这些验收数据。

四个强制区间可以用套件清单一次执行：

```powershell
python -m trade_helper.cli replay-suite .\config\replay_suite.example.json `
  --output .\var\replay-suite.json
```

套件拒绝缺少或多出强制场景的清单，并要求每个场景填写数据来源说明。报告记录每份
输入 CSV 的 SHA-256，保证评审时可以确认使用的是同一份历史输入。
