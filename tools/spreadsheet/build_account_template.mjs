import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = path.resolve(import.meta.dirname, "..", "..");
const outputDir = path.join(projectRoot, "outputs", "account_template");
const previewDir = path.join(outputDir, "previews");
const outputPath = path.join(outputDir, "trade_helper_account_template.xlsx");

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("使用说明");
const snapshots = workbook.worksheets.add("账户快照");
const positions = workbook.worksheets.add("持仓快照");
const trades = workbook.worksheets.add("交易流水");
const cashFlows = workbook.worksheets.add("资金流水");
const manualMarket = workbook.worksheets.add("盘中人工数据");
const dictionary = workbook.worksheets.add("数据字典");

const colors = {
  navy: "#17365D",
  teal: "#0F6B78",
  lightBlue: "#DCE6F1",
  inputYellow: "#FFF2CC",
  lightGreen: "#E2F0D9",
  lightRed: "#FCE4D6",
  grid: "#D9E2F3",
  white: "#FFFFFF",
  black: "#000000",
  blue: "#0000FF",
  green: "#008000",
  gray: "#666666",
};

function styleTitle(sheet, range, title) {
  const target = sheet.getRange(range);
  target.merge();
  target.values = [[title]];
  target.format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 16 },
    verticalAlignment: "center",
  };
  target.format.rowHeight = 30;
}

function styleHeader(range) {
  range.format = {
    fill: colors.teal,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.grid },
  };
  range.format.rowHeight = 30;
}

function styleInput(range) {
  range.format = {
    fill: colors.inputYellow,
    font: { color: colors.blue },
    borders: { preset: "inside", style: "thin", color: colors.grid },
  };
}

function setupSheet(sheet, freezeRows = 3) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(freezeRows);
}

styleTitle(instructions, "A1:H1", "Trade Helper 账户数据导入模板");
instructions.getRange("A3:B11").values = [
  ["项目", "说明"],
  ["用途", "记录无法从公开行情取得的账户私有数据，并供Windows客户端导入。"],
  ["更新顺序", "先更新账户快照和持仓；交易后补交易流水；转入工资、分红和利息记入资金流水。"],
  ["盘中复核", "14:00生成建议前，在“盘中人工数据”填写券商卖一价、IOPV及账户检查项。"],
  ["金额口径", "全部金额使用人民币元；MVP忽略佣金和税费；净现金流由公式计算。"],
  ["数量口径", "ETF份额使用整数；成交记录一行只记录一个方向和一次成交。"],
  ["时间口径", "使用北京时间，格式为 yyyy-mm-dd hh:mm:ss。"],
  ["隐私", "不要填写资金账号、密码、验证码、身份证号或手机号。"],
  ["导入原则", "客户端按列名读取；不要修改工作表名和表头，允许新增数据行。"],
];
instructions.getRange("A3:B3").format = {
  fill: colors.lightBlue,
  font: { bold: true },
  borders: { preset: "all", style: "thin", color: colors.grid },
};
instructions.getRange("A4:B11").format = {
  borders: { preset: "inside", style: "thin", color: colors.grid },
  verticalAlignment: "top",
  wrapText: true,
};
instructions.getRange("A13:B16").values = [
  ["颜色", "含义"],
  ["黄色 / 蓝字", "用户需要填写或确认"],
  ["绿色", "公式或客户端计算结果"],
  ["红色", "缺失或错误时需要处理"],
];
instructions.getRange("A13:B13").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white },
};
instructions.getRange("A14:A14").format.fill = colors.inputYellow;
instructions.getRange("A14:A14").format.font = { color: colors.blue };
instructions.getRange("A15:A15").format.fill = colors.lightGreen;
instructions.getRange("A16:A16").format.fill = colors.lightRed;
instructions.getRange("A1:H16").format.font.name = "Microsoft YaHei";
instructions.getRange("A:A").format.columnWidth = 18;
instructions.getRange("B:B").format.columnWidth = 72;
setupSheet(instructions, 3);

styleTitle(snapshots, "A1:G1", "账户快照（每次生成建议前更新一行）");
snapshots.getRange("A3:G4").values = [
  [
    "snapshot_id", "as_of", "total_assets", "available_cash",
    "frozen_cash", "source", "notes",
  ],
  [
    "SNAP-20260730-1400", new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), 500000,
    350000, 0, "MANUAL", "示例行，正式使用前删除或覆盖",
  ],
];
styleHeader(snapshots.getRange("A3:G3"));
styleInput(snapshots.getRange("A4:G54"));
snapshots.getRange("B4:B54").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
snapshots.getRange("C4:E54").format.numberFormat = "¥#,##0.00;[Red](¥#,##0.00);-";
snapshots.getRange("F4:F54").dataValidation = { rule: { type: "list", values: ["MANUAL", "EXCEL_IMPORT", "APP_FORM"] } };
snapshots.getRange("A:G").format.columnWidth = 18;
snapshots.getRange("A:A").format.columnWidth = 23;
snapshots.getRange("B:B").format.columnWidth = 21;
snapshots.getRange("G:G").format.columnWidth = 34;
setupSheet(snapshots);

styleTitle(positions, "A1:H1", "持仓快照（每个时点、每个标的一行）");
positions.getRange("A3:H6").values = [
  ["snapshot_id", "as_of", "asset_id", "etf_code", "quantity", "broker_market_value", "source", "notes"],
  ["SNAP-20260730-1400", new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "SP500", "513500", 24000, 60000, "MANUAL", "示例"],
  ["SNAP-20260730-1400", new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "NASDAQ", "513100", 30000, 60000, "MANUAL", "示例"],
  ["SNAP-20260730-1400", new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "DIVIDEND", "515450", 21000, 30000, "MANUAL", "示例"],
];
styleHeader(positions.getRange("A3:H3"));
styleInput(positions.getRange("A4:H54"));
positions.getRange("B4:B54").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
positions.getRange("D4:D54").format.numberFormat = "@";
positions.getRange("E4:E54").format.numberFormat = "#,##0";
positions.getRange("F4:F54").format.numberFormat = "¥#,##0.00;[Red](¥#,##0.00);-";
positions.getRange("C4:C54").dataValidation = { rule: { type: "list", values: ["SP500", "NASDAQ", "DIVIDEND", "CASH"] } };
positions.getRange("G4:G54").dataValidation = { rule: { type: "list", values: ["MANUAL", "EXCEL_IMPORT", "APP_FORM"] } };
positions.getRange("A:H").format.columnWidth = 18;
positions.getRange("A:A").format.columnWidth = 23;
positions.getRange("B:B").format.columnWidth = 21;
positions.getRange("H:H").format.columnWidth = 30;
setupSheet(positions);

styleTitle(trades, "A1:M1", "交易流水（一行记录一次实际成交）");
trades.getRange("A3:M4").values = [
  [
    "trade_id", "trade_time", "asset_id", "etf_code", "side", "quantity",
    "price", "gross_amount", "net_cash_flow", "status", "order_id", "source", "notes",
  ],
  [
    "TRD-20260730-001", new Date(Date.UTC(2026, 6, 30, 14, 10, 0)), "DIVIDEND",
    "515450", "BUY", 6800, 1.458, null, null, "FILLED", "", "MANUAL", "示例行",
  ],
];
trades.getRange("H4").formulas = [["=F4*G4"]];
trades.getRange("I4").formulas = [['=IF(E4="BUY",-H4,H4)']];
trades.getRange("H4:H104").fillDown();
trades.getRange("I4:I104").fillDown();
styleHeader(trades.getRange("A3:M3"));
styleInput(trades.getRange("A4:G104"));
styleInput(trades.getRange("J4:M104"));
trades.getRange("H4:H104").format = { fill: colors.lightGreen, font: { color: colors.black } };
trades.getRange("I4:I104").format = { fill: colors.lightGreen, font: { color: colors.black } };
trades.getRange("B4:B104").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
trades.getRange("D4:D104").format.numberFormat = "@";
trades.getRange("F4:F104").format.numberFormat = "#,##0";
trades.getRange("G4:I104").format.numberFormat = "¥#,##0.000;[Red](¥#,##0.000);-";
trades.getRange("C4:C104").dataValidation = { rule: { type: "list", values: ["SP500", "NASDAQ", "DIVIDEND"] } };
trades.getRange("E4:E104").dataValidation = { rule: { type: "list", values: ["BUY", "SELL"] } };
trades.getRange("J4:J104").dataValidation = { rule: { type: "list", values: ["SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"] } };
trades.getRange("L4:L104").dataValidation = { rule: { type: "list", values: ["MANUAL", "EXCEL_IMPORT", "APP_FORM", "BROKER_CSV"] } };
trades.getRange("A:M").format.columnWidth = 16;
trades.getRange("A:A").format.columnWidth = 23;
trades.getRange("B:B").format.columnWidth = 21;
trades.getRange("M:M").format.columnWidth = 30;
setupSheet(trades);

styleTitle(cashFlows, "A1:I1", "资金流水（工资转入、提取、分红、利息和费用）");
cashFlows.getRange("A3:I4").values = [
  ["flow_id", "flow_time", "flow_type", "amount", "asset_id", "etf_code", "description", "source", "notes"],
  ["FLOW-20260701-001", new Date(Date.UTC(2026, 6, 1, 9, 0, 0)), "DEPOSIT", 16000, "", "", "月度新增资金", "MANUAL", "示例行"],
];
styleHeader(cashFlows.getRange("A3:I3"));
styleInput(cashFlows.getRange("A4:I104"));
cashFlows.getRange("B4:B104").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
cashFlows.getRange("D4:D104").format.numberFormat = "¥#,##0.00;[Red](¥#,##0.00);-";
cashFlows.getRange("F4:F104").format.numberFormat = "@";
cashFlows.getRange("C4:C104").dataValidation = { rule: { type: "list", values: ["DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "TAX", "ADJUSTMENT"] } };
cashFlows.getRange("E4:E104").dataValidation = { rule: { type: "list", values: ["", "SP500", "NASDAQ", "DIVIDEND", "CASH"] } };
cashFlows.getRange("H4:H104").dataValidation = { rule: { type: "list", values: ["MANUAL", "EXCEL_IMPORT", "APP_FORM", "BROKER_CSV"] } };
cashFlows.getRange("A:I").format.columnWidth = 17;
cashFlows.getRange("B:B").format.columnWidth = 21;
cashFlows.getRange("G:G").format.columnWidth = 28;
cashFlows.getRange("I:I").format.columnWidth = 28;
setupSheet(cashFlows);

styleTitle(manualMarket, "A1:M1", "盘中人工数据（生成建议前从券商客户端确认）");
manualMarket.getRange("A3:M6").values = [
  [
    "observed_at", "asset_id", "etf_code", "broker_bid1", "broker_ask1",
    "broker_iopv", "available_cash", "pending_buy_amount", "pending_sell_quantity",
    "trading_status", "source", "confirmed_by_user", "notes",
  ],
  [new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "SP500", "513500", null, null, null, 350000, 0, 0, "NORMAL", "GTHT_CLIENT", false, ""],
  [new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "NASDAQ", "513100", null, null, null, 350000, 0, 0, "NORMAL", "GTHT_CLIENT", false, ""],
  [new Date(Date.UTC(2026, 6, 30, 14, 0, 0)), "DIVIDEND", "515450", null, null, null, 350000, 0, 0, "NORMAL", "GTHT_CLIENT", false, ""],
];
styleHeader(manualMarket.getRange("A3:M3"));
styleInput(manualMarket.getRange("A4:M54"));
manualMarket.getRange("A4:A54").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
manualMarket.getRange("C4:C54").format.numberFormat = "@";
manualMarket.getRange("D4:H54").format.numberFormat = "¥#,##0.000;[Red](¥#,##0.000);-";
manualMarket.getRange("I4:I54").format.numberFormat = "#,##0";
manualMarket.getRange("B4:B54").dataValidation = { rule: { type: "list", values: ["SP500", "NASDAQ", "DIVIDEND"] } };
manualMarket.getRange("J4:J54").dataValidation = { rule: { type: "list", values: ["NORMAL", "HALTED", "SUSPENDED", "UNKNOWN"] } };
manualMarket.getRange("K4:K54").dataValidation = { rule: { type: "list", values: ["GTHT_CLIENT", "OTHER_BROKER", "MANUAL"] } };
manualMarket.getRange("L4:L54").dataValidation = { rule: { type: "list", values: [true, false] } };
manualMarket.getRange("A:M").format.columnWidth = 17;
manualMarket.getRange("A:A").format.columnWidth = 21;
manualMarket.getRange("M:M").format.columnWidth = 30;
setupSheet(manualMarket);

styleTitle(dictionary, "A1:G1", "数据字典与导入规则");
dictionary.getRange("A3:G19").values = [
  ["工作表", "字段", "类型", "必填", "示例", "说明", "APP校验"],
  ["账户快照", "snapshot_id", "文本", "是", "SNAP-20260730-1400", "一次账户快照的唯一标识", "不得重复"],
  ["账户快照", "as_of", "日期时间", "是", "2026-07-30 14:00:00", "北京时间", "不得晚于当前时间"],
  ["账户快照", "available_cash", "金额", "是", "350000", "券商可用于买入的资金", "大于等于0"],
  ["持仓快照", "asset_id", "枚举", "是", "SP500", "策略资产ID", "必须在枚举内"],
  ["持仓快照", "etf_code", "文本", "是", "513500", "证券代码保留前导零", "6位数字"],
  ["持仓快照", "quantity", "整数", "是", "24000", "实际持仓份额", "大于等于0"],
  ["交易流水", "trade_id", "文本", "是", "TRD-20260730-001", "实际成交唯一标识", "不得重复"],
  ["交易流水", "side", "枚举", "是", "BUY", "买卖方向", "BUY或SELL"],
  ["交易流水", "quantity", "整数", "是", "6800", "实际成交份额", "大于0"],
  ["交易流水", "price", "金额", "是", "1.458", "实际成交价格", "大于0"],
  ["资金流水", "flow_type", "枚举", "是", "DEPOSIT", "资金变化原因", "必须在枚举内"],
  ["资金流水", "amount", "金额", "是", "16000", "转入/收入为正，转出/费用为负", "不等于0"],
  ["盘中人工数据", "broker_ask1", "价格", "条件必填", "2.040", "券商卖一价", "大于0且时间有效"],
  ["盘中人工数据", "broker_iopv", "价格", "条件必填", "1.900", "券商IOPV或参考净值", "大于0且时间有效"],
  ["盘中人工数据", "confirmed_by_user", "布尔", "是", "TRUE", "用户已核对券商数据", "必须为TRUE才可执行"],
  ["全部", "notes", "文本", "否", "", "补充说明，不参与计算", "最长500字符"],
];
styleHeader(dictionary.getRange("A3:G3"));
dictionary.getRange("A4:G19").format = {
  borders: { preset: "inside", style: "thin", color: colors.grid },
  verticalAlignment: "top",
  wrapText: true,
};
dictionary.getRange("A4:B19").format.font = { color: colors.green };
dictionary.getRange("A:G").format.columnWidth = 19;
dictionary.getRange("F:G").format.columnWidth = 34;
setupSheet(dictionary);

for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange();
  used.format.font.name = "Microsoft YaHei";
  used.format.verticalAlignment = "center";
}

await fs.mkdir(previewDir, { recursive: true });
for (const sheet of workbook.worksheets.items) {
  const preview = await workbook.render({
    sheetName: sheet.name,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${sheet.name}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const keyInspection = await workbook.inspect({
  kind: "table",
  range: "交易流水!A3:M6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 13,
});
console.log(keyInspection.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
console.log(outputPath);
