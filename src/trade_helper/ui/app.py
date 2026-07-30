from __future__ import annotations

import tkinter as tk
import os
import sys
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from trade_helper.execution import AdviceStatus
from trade_helper.ui.theme import COLORS, FONTS, status_color
from trade_helper.ui.controller import (
    AccountForm, DesktopController, MarketCollectionSummary, PositionForm,
)
from trade_helper.ui.view_model import (
    DashboardRepository,
    DashboardViewModel,
    empty_dashboard,
)


@dataclass(frozen=True)
class AssetView:
    name: str
    code: str
    weight: Decimal
    target: Decimal
    drawdown: Decimal
    premium: Decimal
    state: str
    accent: str


class TradeHelperApp(tk.Tk):
    def __init__(
        self,
        model: DashboardViewModel | None = None,
        database: str | Path = "var/account.db",
    ) -> None:
        super().__init__()
        self.database = Path(database)
        self.controller = DesktopController(self.database)
        self.model = model or empty_dashboard()
        self.title("Trade Helper · Personal V1")
        self.geometry("1440x900")
        self.minsize(1180, 760)
        self.configure(bg=COLORS["window"])
        self._configure_styles()
        self._build_shell()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Vertical.TScrollbar",
            background=COLORS["surface_hover"],
            troughcolor=COLORS["window"],
            bordercolor=COLORS["window"],
            arrowcolor=COLORS["muted"],
        )

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        content = tk.Frame(self, bg=COLORS["window"])
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self._build_header(content)
        self._build_dashboard(content)

    def _build_sidebar(self) -> None:
        sidebar = tk.Frame(self, bg=COLORS["sidebar"], width=224)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        brand = tk.Frame(sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=24, pady=(26, 34))
        tk.Label(
            brand, text="◈", font=("Segoe UI Symbol", 24),
            fg=COLORS["cyan"], bg=COLORS["sidebar"],
        ).pack(side="left")
        tk.Label(
            brand, text="TRADE\nHELPER", justify="left", font=FONTS["title"],
            fg=COLORS["text"], bg=COLORS["sidebar"],
        ).pack(side="left", padx=10)
        for index, (icon, label) in enumerate(
            (
                ("⌂", "总览"),
                ("◎", "账户"),
                ("⌁", "数据中心"),
                ("◇", "今日建议"),
                ("↻", "执行反馈"),
                ("◫", "策略状态"),
                ("◷", "历史审计"),
                ("▣", "备份恢复"),
            )
        ):
            active = index == 0
            item = tk.Frame(
                sidebar,
                bg=COLORS["cyan_dim"] if active else COLORS["sidebar"],
                height=48,
            )
            item.pack(fill="x", padx=12, pady=3)
            item.pack_propagate(False)
            tk.Label(
                item, text=icon, width=3, font=("Segoe UI Symbol", 14),
                fg=COLORS["cyan"] if active else COLORS["muted"],
                bg=item["bg"],
            ).pack(side="left", padx=(10, 0))
            tk.Label(
                item, text=label, font=FONTS["body"],
                fg=COLORS["text"] if active else COLORS["muted"],
                bg=item["bg"],
            ).pack(side="left", padx=4)
            if label == "历史审计":
                for widget in (item, *item.winfo_children()):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _: self._open_history())
            if label == "数据中心":
                for widget in (item, *item.winfo_children()):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _: self._open_data_center())
            if label == "策略状态":
                for widget in (item, *item.winfo_children()):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _: self._open_strategy_state())
            if label == "备份恢复":
                for widget in (item, *item.winfo_children()):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _: self._open_backup_center())
        footer = tk.Frame(sidebar, bg=COLORS["sidebar"])
        footer.pack(side="bottom", fill="x", padx=22, pady=24)
        tk.Label(
            footer, text="PERSONAL V1", font=FONTS["mono"],
            fg=COLORS["cyan"], bg=COLORS["sidebar"],
        ).pack(anchor="w")
        tk.Label(
            footer, text="本地运行 · 不连接券商", font=FONTS["small"],
            fg=COLORS["muted"], bg=COLORS["sidebar"],
        ).pack(anchor="w", pady=(4, 0))

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=COLORS["window"], height=92)
        header.grid(row=0, column=0, sticky="ew", padx=32)
        header.grid_propagate(False)
        title = tk.Frame(header, bg=COLORS["window"])
        title.pack(side="left", fill="y")
        tk.Label(
            title, text="投资组合总览", font=FONTS["hero"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).pack(anchor="w", pady=(19, 0))
        tk.Label(
            title,
            text=(
                f"最近决策 {self.model.latest_decision_at:%Y-%m-%d %H:%M}"
                if self.model.latest_decision_at else "尚无决策记录 · 下一次决策 14:00"
            ),
            font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(anchor="w")
        status = tk.Frame(
            header, bg=COLORS["surface"], highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        status.pack(side="right", pady=25)
        tk.Button(
            header, text="导入账户 Excel", command=self._import_excel,
            font=FONTS["body"], fg=COLORS["window"], bg=COLORS["cyan"],
            activebackground=COLORS["green"], relief="flat",
            padx=16, pady=7, cursor="hand2",
        ).pack(side="right", padx=(0, 12), pady=25)
        tk.Button(
            header, text="录入账户", command=self._record_account,
            font=FONTS["body"], fg=COLORS["text"],
            bg=COLORS["surface_hover"], activebackground=COLORS["blue"],
            relief="flat", padx=16, pady=7, cursor="hand2",
        ).pack(side="right", padx=(0, 8), pady=25)
        tk.Label(
            status, text="●", fg=status_color(self.model.data_status.value),
            bg=COLORS["surface"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(14, 6), pady=8)
        tk.Label(
            status,
            text={
                "READY": "数据就绪",
                "REVIEW": "需要复核",
                "BLOCKED": "数据阻断",
            }[self.model.data_status.value],
            fg=COLORS["text"], bg=COLORS["surface"],
            font=FONTS["small"],
        ).pack(side="left", padx=(0, 14))

    def _build_dashboard(self, parent: tk.Widget) -> None:
        canvas = tk.Canvas(parent, bg=COLORS["window"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=COLORS["window"])
        body.bind(
            "<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metric")
        account_state = (
            "已对账" if self.model.reconciliation_status == "RECONCILED" else "待对账"
        )
        for index, values in enumerate(
            (
                ("总资产", self._money(self.model.total_assets_cny), "来自最新账户快照", COLORS["cyan"]),
                ("策略现金", self._money(self.model.cash_cny), f"安全线 {self._money(self.model.cash_floor_cny)}", COLORS["green"]),
                ("今日可买", self._money(self.model.today_buy_limit_cny), "受现金与单日上限约束", COLORS["blue"]),
                ("账户状态", account_state, self.model.reconciliation_status, status_color(self.model.reconciliation_status)),
            )
        ):
            self._metric_card(body, index, *values)
        asset_section = tk.Frame(body, bg=COLORS["window"])
        asset_section.grid(row=1, column=0, columnspan=4, sticky="ew", padx=32, pady=8)
        asset_section.grid_columnconfigure((0, 1, 2), weight=1, uniform="asset")
        tk.Label(
            asset_section, text="资产雷达", font=FONTS["title"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(12, 14))
        accent_by_asset = {
            "SP500": COLORS["cyan"],
            "NASDAQ": COLORS["blue"],
            "DIVIDEND": COLORS["green"],
        }
        assets = tuple(
            AssetView(
                item.name, item.code, item.weight, item.target_weight,
                item.drawdown or Decimal("0"), item.premium or Decimal("0"),
                item.state, accent_by_asset.get(item.asset_id, COLORS["cyan"]),
            )
            for item in self.model.assets
        )
        for index, asset in enumerate(assets):
            self._asset_card(asset_section, index, asset)
        lower = tk.Frame(body, bg=COLORS["window"])
        lower.grid(row=2, column=0, columnspan=4, sticky="ew", padx=32, pady=(16, 32))
        lower.grid_columnconfigure(0, weight=3)
        lower.grid_columnconfigure(1, weight=2)
        self._advice_panel(lower)
        self._cash_panel(lower)

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(
            parent, bg=COLORS["surface"], highlightthickness=1,
            highlightbackground=COLORS["border"],
        )

    def _metric_card(
        self, parent: tk.Widget, column: int, label: str, value: str,
        detail: str, accent: str,
    ) -> None:
        card = self._card(parent)
        card.grid(row=0, column=column, sticky="nsew", padx=(32 if column == 0 else 8, 32 if column == 3 else 8), pady=(4, 18))
        tk.Frame(card, bg=accent, height=3).pack(fill="x")
        tk.Label(card, text=label, font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"]).pack(anchor="w", padx=18, pady=(15, 2))
        tk.Label(card, text=value, font=FONTS["metric"], fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w", padx=18)
        tk.Label(card, text=detail, font=FONTS["small"], fg=accent, bg=COLORS["surface"]).pack(anchor="w", padx=18, pady=(4, 16))

    def _asset_card(self, parent: tk.Widget, column: int, asset: AssetView) -> None:
        card = self._card(parent)
        card.grid(row=1, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0 if column == 2 else 8))
        top = tk.Frame(card, bg=COLORS["surface"])
        top.pack(fill="x", padx=18, pady=(17, 12))
        tk.Label(top, text=asset.name, font=FONTS["title"], fg=COLORS["text"], bg=COLORS["surface"]).pack(side="left")
        tk.Label(top, text=asset.code, font=FONTS["mono"], fg=asset.accent, bg=COLORS["surface"]).pack(side="right")
        tk.Label(card, text=f"{asset.weight:.0%}", font=FONTS["metric"], fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w", padx=18)
        tk.Label(card, text=f"目标 {asset.target:.0%}", font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"]).pack(anchor="w", padx=18)
        track = tk.Canvas(card, height=8, bg=COLORS["surface"], highlightthickness=0)
        track.pack(fill="x", padx=18, pady=13)
        track.bind("<Configure>", lambda event, c=track, a=asset: self._draw_weight(c, event.width, a))
        facts = tk.Frame(card, bg=COLORS["surface"])
        facts.pack(fill="x", padx=18, pady=(0, 16))
        for label, value in (("回撤", f"{asset.drawdown:.2%}"), ("溢价", f"{asset.premium:.2%}")):
            group = tk.Frame(facts, bg=COLORS["surface"])
            group.pack(side="left", expand=True, fill="x")
            tk.Label(group, text=label, font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"]).pack(anchor="w")
            tk.Label(group, text=value, font=("Segoe UI", 12, "bold"), fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w")
        tk.Label(card, text=asset.state, font=FONTS["small"], fg=asset.accent, bg=COLORS["cyan_dim"], padx=10, pady=5).pack(anchor="w", padx=18, pady=(0, 18))

    @staticmethod
    def _draw_weight(canvas: tk.Canvas, width: int, asset: AssetView) -> None:
        canvas.delete("all")
        canvas.create_rectangle(0, 2, width, 6, fill=COLORS["border"], outline="")
        ratio = min(1.0, max(0.0, float(asset.weight / asset.target)))
        canvas.create_rectangle(0, 2, width * ratio, 6, fill=asset.accent, outline="")

    def _advice_panel(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(card, text="今日决策", font=FONTS["title"], fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w", padx=20, pady=(18, 4))
        decision_copy = (
            f"最近状态：{self.model.latest_decision_status}"
            if self.model.latest_decision_status else "等待 14:00 数据确认后生成"
        )
        tk.Label(card, text=decision_copy, font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"]).pack(anchor="w", padx=20)
        if not self.model.open_advices:
            line = tk.Frame(card, bg=COLORS["cyan_dim"], highlightthickness=1, highlightbackground=COLORS["cyan"])
            line.pack(fill="x", padx=20, pady=18)
            tk.Label(line, text="◇", font=("Segoe UI Symbol", 22), fg=COLORS["cyan"], bg=COLORS["cyan_dim"]).pack(side="left", padx=16, pady=14)
            copy = tk.Frame(line, bg=COLORS["cyan_dim"])
            copy.pack(side="left", fill="x", expand=True)
            tk.Label(copy, text="当前无待处理建议", font=FONTS["title"], fg=COLORS["text"], bg=COLORS["cyan_dim"]).pack(anchor="w")
            tk.Label(copy, text="系统将在数据、对账与风控全部通过后显示建议", font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["cyan_dim"]).pack(anchor="w")
            return
        for advice in self.model.open_advices[:4]:
            row = tk.Frame(
                card, bg=COLORS["cyan_dim"], highlightthickness=1,
                highlightbackground=COLORS["border"],
            )
            row.pack(fill="x", padx=20, pady=(10, 0))
            copy = tk.Frame(row, bg=COLORS["cyan_dim"])
            copy.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            side_text = "买入" if advice.side == "BUY" else "卖出"
            tk.Label(
                copy,
                text=f"{side_text} {advice.code} · {advice.proposed_quantity:,} 份",
                font=FONTS["title"], fg=COLORS["text"], bg=COLORS["cyan_dim"],
            ).pack(anchor="w")
            tk.Label(
                copy,
                text=(
                    f"限价 {advice.limit_price:.3f} · 已成交 "
                    f"{advice.filled_quantity:,} · {advice.status}"
                ),
                font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["cyan_dim"],
            ).pack(anchor="w")
            actions = tk.Frame(row, bg=COLORS["cyan_dim"])
            actions.pack(side="right", padx=10)
            self._action_button(
                actions, "未操作",
                lambda item=advice: self._record_attempt(
                    item.advice_id, AdviceStatus.NOT_ATTEMPTED
                ),
                COLORS["muted"],
            ).pack(side="left", padx=3)
            self._action_button(
                actions, "已下单",
                lambda item=advice: self._record_attempt(
                    item.advice_id, AdviceStatus.ORDER_SUBMITTED
                ),
                COLORS["blue"],
            ).pack(side="left", padx=3)
            self._action_button(
                actions, "回填成交",
                lambda item=advice: self._record_fill(
                    item.advice_id,
                    item.proposed_quantity - item.filled_quantity,
                    item.limit_price,
                ),
                COLORS["green"],
            ).pack(side="left", padx=3)
        tk.Frame(card, bg=COLORS["surface"], height=14).pack()

    def _cash_panel(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(card, text="虚拟资金池", font=FONTS["title"], fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w", padx=20, pady=(18, 14))
        pool_colors = (
            COLORS["cyan"], COLORS["blue"], "#A079FF",
            COLORS["green"], COLORS["yellow"],
        )
        for (label, value), color in zip(self.model.cash_pools, pool_colors):
            row = tk.Frame(card, bg=COLORS["surface"])
            row.pack(fill="x", padx=20, pady=5)
            tk.Label(row, text="●", fg=color, bg=COLORS["surface"]).pack(side="left")
            tk.Label(row, text=label, font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"]).pack(side="left", padx=8)
            tk.Label(row, text=self._money(value), font=FONTS["mono"], fg=COLORS["text"], bg=COLORS["surface"]).pack(side="right")

    @staticmethod
    def _money(value: Decimal) -> str:
        return f"¥{value:,.0f}"

    def _import_excel(self) -> None:
        workbook = filedialog.askopenfilename(
            parent=self,
            title="选择 Trade Helper 账户工作簿",
            filetypes=(("Excel 工作簿", "*.xlsx"), ("所有文件", "*.*")),
        )
        if not workbook:
            return
        try:
            summary = self.controller.preview_excel(workbook)
        except Exception as error:
            messagebox.showerror("无法读取工作簿", str(error), parent=self)
            return
        counts = summary.row_counts
        lines = [
            f"文件：{summary.source_name}",
            f"账户快照：{counts['snapshots']}",
            f"持仓行：{counts['positions']}",
            f"成交行：{counts['trades']}",
            f"资金流水：{counts['cash_flows']}",
        ]
        if not summary.valid:
            issue_lines = [
                f"{item.sheet} 第{item.row}行：{item.message}"
                for item in summary.issues[:8]
            ]
            messagebox.showerror(
                "导入校验未通过",
                "\n".join((*lines, "", *issue_lines)),
                parent=self,
            )
            return
        confirmed = messagebox.askyesno(
            "确认原子导入",
            "\n".join((*lines, "", "校验通过。确认将整批数据写入本地账本？")),
            parent=self,
        )
        if not confirmed:
            return
        result = self.controller.commit_excel(summary.content_hash)
        if result.imported or result.duplicate:
            messagebox.showinfo("导入完成", result.message, parent=self)
            self._reload_dashboard()
        else:
            messagebox.showerror("导入冲突", result.message, parent=self)

    def _reload_dashboard(self) -> None:
        self.model = DashboardRepository(self.database).load()
        for child in self.winfo_children():
            child.destroy()
        self._build_shell()

    def _action_button(
        self, parent: tk.Widget, text: str, command, color: str
    ) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, font=FONTS["small"],
            fg=COLORS["text"], bg=COLORS["surface_hover"],
            activebackground=color, activeforeground=COLORS["window"],
            relief="flat", padx=9, pady=6, cursor="hand2",
        )

    def _record_attempt(self, advice_id: str, status: AdviceStatus) -> None:
        try:
            self.controller.record_attempt(advice_id, status)
        except Exception as error:
            messagebox.showerror("反馈失败", str(error), parent=self)
            return
        self._reload_dashboard()

    def _record_fill(
        self, advice_id: str, remaining_quantity: int, suggested_price: Decimal
    ) -> None:
        quantity = simpledialog.askinteger(
            "实际成交数量",
            f"请输入实际成交份额（剩余 {remaining_quantity:,}）",
            parent=self, minvalue=1, maxvalue=remaining_quantity,
        )
        if quantity is None:
            return
        price = simpledialog.askfloat(
            "实际成交价格",
            "请输入券商显示的实际成交价",
            parent=self, minvalue=0.001,
            initialvalue=float(suggested_price),
        )
        if price is None:
            return
        try:
            status = self.controller.record_fill(
                advice_id, quantity, Decimal(str(price))
            )
        except Exception as error:
            messagebox.showerror("成交回填失败", str(error), parent=self)
            return
        messagebox.showinfo("成交已记录", f"当前状态：{status.value}", parent=self)
        self._reload_dashboard()

    def _open_history(self) -> None:
        window = tk.Toplevel(self)
        window.title("Trade Helper · 历史审计")
        window.geometry("1100x680")
        window.configure(bg=COLORS["window"])
        tk.Label(
            window, text="历史审计", font=FONTS["hero"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(
            window, text="决策、实际成交与资金流水按时间统一展示",
            font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(0, 18))
        style = ttk.Style(window)
        style.configure(
            "Audit.Treeview",
            background=COLORS["surface"], fieldbackground=COLORS["surface"],
            foreground=COLORS["text"], rowheight=34, borderwidth=0,
            font=FONTS["small"],
        )
        style.configure(
            "Audit.Treeview.Heading",
            background=COLORS["surface_hover"], foreground=COLORS["cyan"],
            relief="flat", font=FONTS["small"],
        )
        frame = tk.Frame(window, bg=COLORS["window"])
        frame.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        columns = ("time", "category", "reference", "status", "summary")
        tree = ttk.Treeview(
            frame, columns=columns, show="headings", style="Audit.Treeview"
        )
        widths = (170, 80, 190, 150, 430)
        labels = ("时间", "类别", "记录 ID", "状态", "摘要")
        for column, width, label in zip(columns, widths, labels):
            tree.heading(column, text=label)
            tree.column(column, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for record in DashboardRepository(self.database).load_history():
            tree.insert(
                "", "end",
                values=(
                    record.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                    record.category, record.reference_id, record.status,
                    record.summary,
                ),
            )

    def _record_account(self) -> None:
        total = simpledialog.askfloat(
            "账户总资产", "请输入券商显示的账户总资产（元）",
            parent=self, minvalue=0,
        )
        if total is None:
            return
        cash = simpledialog.askfloat(
            "可用现金", "请输入货币基金/现金总市值（元）",
            parent=self, minvalue=0,
        )
        if cash is None:
            return
        definitions = (
            ("SP500", "513500", "标普500"),
            ("NASDAQ", "513100", "纳指100"),
            ("DIVIDEND", "515450", "红利低波"),
        )
        positions = []
        for asset_id, code, name in definitions:
            quantity = simpledialog.askinteger(
                f"{name}份额", f"请输入 {code} 的实际持仓份额",
                parent=self, minvalue=0,
            )
            if quantity is None:
                return
            value = simpledialog.askfloat(
                f"{name}市值", f"请输入 {code} 的券商市值（元）",
                parent=self, minvalue=0,
            )
            if value is None:
                return
            positions.append(
                PositionForm(
                    asset_id, code, quantity, Decimal(str(value))
                )
            )
        try:
            snapshot_id = self.controller.record_account(
                AccountForm(
                    Decimal(str(total)), Decimal(str(cash)), tuple(positions)
                )
            )
        except Exception as error:
            messagebox.showerror("账户校验未通过", str(error), parent=self)
            return
        messagebox.showinfo(
            "账户快照已保存", f"快照 ID：{snapshot_id}", parent=self
        )
        self._reload_dashboard()

    def _open_data_center(self) -> None:
        window = tk.Toplevel(self)
        window.title("Trade Helper · 数据中心")
        window.geometry("1180x680")
        window.configure(bg=COLORS["window"])
        tk.Label(
            window, text="数据中心", font=FONTS["hero"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(
            window,
            text="最新多源快照、来源覆盖和阻断原因",
            font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(0, 10))
        actions = tk.Frame(window, bg=COLORS["window"])
        actions.pack(fill="x", padx=28, pady=(0, 14))
        collection_status = tk.StringVar(value="选择当日补充 JSON 后采集多源行情")
        collect_button = tk.Button(
            actions,
            text="采集当日行情",
            command=lambda: self._collect_market_from_file(
                window, tree, collection_status, collect_button
            ),
            bg=COLORS["cyan"], fg=COLORS["window"],
            activebackground=COLORS["cyan_soft"],
            relief="flat", padx=18, pady=8, cursor="hand2",
            font=FONTS["small"],
        )
        collect_button.pack(side="left")
        tk.Label(
            actions, textvariable=collection_status, font=FONTS["small"],
            fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(side="left", padx=14)
        style = ttk.Style(window)
        style.configure(
            "Audit.Treeview",
            background=COLORS["surface"], fieldbackground=COLORS["surface"],
            foreground=COLORS["text"], rowheight=34, borderwidth=0,
            font=FONTS["small"],
        )
        style.configure(
            "Audit.Treeview.Heading",
            background=COLORS["surface_hover"], foreground=COLORS["cyan"],
            relief="flat", font=FONTS["small"],
        )
        frame = tk.Frame(window, bg=COLORS["window"])
        frame.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        columns = (
            "symbol", "time", "status", "quotes", "valuations",
            "others", "reasons",
        )
        tree = ttk.Treeview(
            frame, columns=columns, show="headings", style="Audit.Treeview"
        )
        definitions = (
            ("symbol", "ETF", 80),
            ("time", "快照时间", 165),
            ("status", "状态", 90),
            ("quotes", "行情源", 150),
            ("valuations", "估值源", 150),
            ("others", "其他来源", 230),
            ("reasons", "阻断原因", 300),
        )
        for column, label, width in definitions:
            tree.heading(column, text=label)
            tree.column(column, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._populate_market_tree(tree)

    def _populate_market_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for detail in DashboardRepository(self.database).load_market_details():
            tree.insert(
                "", "end",
                values=(
                    detail.symbol,
                    detail.observed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    detail.readiness,
                    ", ".join(detail.quote_sources) or "缺失",
                    ", ".join(detail.valuation_sources) or "缺失",
                    ", ".join(detail.other_sources) or "缺失",
                    "；".join(detail.reasons) or "无",
                ),
            )

    def _collect_market_from_file(
        self,
        window: tk.Toplevel,
        tree: ttk.Treeview,
        status: tk.StringVar,
        button: tk.Button,
    ) -> None:
        supplement = filedialog.askopenfilename(
            parent=window,
            title="选择当日行情补充文件",
            filetypes=(("JSON 文件", "*.json"), ("所有文件", "*.*")),
        )
        if not supplement:
            return
        try:
            config = self._strategy_config_path()
        except FileNotFoundError as error:
            messagebox.showerror("配置缺失", str(error), parent=window)
            return
        button.configure(state="disabled")
        status.set("正在连接行情源并校验数据…")

        def collect() -> None:
            try:
                result = self.controller.collect_market(supplement, config)
            except Exception as error:
                window.after(
                    0, lambda caught=error: self._finish_market_collection(
                        window, tree, status, button, None, caught
                    )
                )
            else:
                window.after(
                    0, lambda collected=result: self._finish_market_collection(
                        window, tree, status, button, collected, None
                    )
                )

        threading.Thread(target=collect, daemon=True).start()

    def _finish_market_collection(
        self,
        window: tk.Toplevel,
        tree: ttk.Treeview,
        status: tk.StringVar,
        button: tk.Button,
        result: MarketCollectionSummary | None,
        error: Exception | None,
    ) -> None:
        button.configure(state="normal")
        if error is not None:
            status.set("采集失败")
            messagebox.showerror("行情采集失败", str(error), parent=window)
            return
        assert result is not None
        self._populate_market_tree(tree)
        self._reload_dashboard()
        ready_count = sum(
            readiness == "READY" for _, readiness, _ in result.snapshots
        )
        if result.usable:
            label = "采集完成（降级可用）" if result.degraded else "采集完成"
            status.set(f"{label} · READY {ready_count}/3")
            if result.degraded:
                messagebox.showwarning(
                    "行情降级可用",
                    "全部标的已 READY，但部分公共源失败；异常已写入审计记录。",
                    parent=window,
                )
        else:
            status.set(f"采集已阻断 · READY {ready_count}/3")
            messagebox.showwarning(
                "行情未就绪",
                "至少一个标的未达到 READY，系统不会生成交易建议。"
                "请查看表格中的阻断原因。",
                parent=window,
            )

    @staticmethod
    def _strategy_config_path() -> Path:
        configured = os.environ.get("TRADE_HELPER_CONFIG")
        candidates = []
        if configured:
            candidates.append(Path(configured))
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.append(Path(bundle_root) / "config" / "personal_v1.json")
        candidates.extend(
            (
                Path.cwd() / "config" / "personal_v1.json",
                Path(__file__).resolve().parents[3]
                / "config" / "personal_v1.json",
            )
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(
            "找不到 personal_v1.json；可通过 TRADE_HELPER_CONFIG 指定路径"
        )

    def _open_backup_center(self) -> None:
        window = tk.Toplevel(self)
        window.title("Trade Helper · 备份与恢复")
        window.geometry("640x360")
        window.configure(bg=COLORS["window"])
        tk.Label(
            window, text="备份与恢复", font=FONTS["hero"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(26, 6))
        tk.Label(
            window,
            text="备份包含本地账户、建议、成交和策略状态。恢复前会自动保存当前数据库。",
            wraplength=570, justify="left", font=FONTS["body"],
            fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(0, 24))
        card = self._card(window)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        tk.Button(
            card, text="创建校验备份",
            command=lambda: self._create_backup_from_client(window),
            bg=COLORS["cyan"], fg=COLORS["window"], relief="flat",
            padx=20, pady=10, cursor="hand2", font=FONTS["body"],
        ).pack(anchor="w", padx=22, pady=(24, 12))
        tk.Button(
            card, text="从备份恢复",
            command=lambda: self._restore_backup_from_client(window),
            bg=COLORS["surface_hover"], fg=COLORS["text"], relief="flat",
            padx=20, pady=10, cursor="hand2", font=FONTS["body"],
        ).pack(anchor="w", padx=22)
        tk.Label(
            card,
            text="恢复操作会校验格式、大小、SHA-256 和 SQLite 完整性。",
            font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["surface"],
        ).pack(anchor="w", padx=22, pady=(16, 20))

    def _create_backup_from_client(self, window: tk.Toplevel) -> None:
        destination = filedialog.asksaveasfilename(
            parent=window,
            title="保存 Trade Helper 备份",
            defaultextension=".thbackup",
            filetypes=(("Trade Helper 备份", "*.thbackup"),),
        )
        if not destination:
            return
        try:
            manifest = self.controller.create_database_backup(destination)
        except Exception as error:
            messagebox.showerror("备份失败", str(error), parent=window)
            return
        messagebox.showinfo(
            "备份完成",
            f"文件：{destination}\n"
            f"大小：{manifest.database_size} 字节\n"
            f"SHA-256：{manifest.database_sha256}",
            parent=window,
        )

    def _restore_backup_from_client(self, window: tk.Toplevel) -> None:
        source = filedialog.askopenfilename(
            parent=window,
            title="选择 Trade Helper 备份",
            filetypes=(("Trade Helper 备份", "*.thbackup"),),
        )
        if not source:
            return
        if not messagebox.askyesno(
            "确认恢复",
            "将用所选备份替换当前本地数据库。\n"
            "系统会先自动备份当前数据库，是否继续？",
            parent=window,
        ):
            return
        try:
            result = self.controller.restore_database_backup(source)
        except Exception as error:
            messagebox.showerror("恢复失败", str(error), parent=window)
            return
        self._reload_dashboard()
        safety = (
            str(result.safety_backup)
            if result.safety_backup is not None else "当前数据库原先不存在"
        )
        messagebox.showinfo(
            "恢复完成",
            f"数据库已通过完整性校验并恢复。\n恢复前安全备份：{safety}",
            parent=window,
        )

    def _open_strategy_state(self) -> None:
        versions, levels = DashboardRepository(
            self.database
        ).load_config_versions()
        window = tk.Toplevel(self)
        window.title("Trade Helper · 策略状态")
        window.geometry("1040x720")
        window.configure(bg=COLORS["window"])
        tk.Label(
            window, text="策略版本与状态机", font=FONTS["hero"],
            fg=COLORS["text"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(
            window,
            text="只读审计视图 · 配置版本不可原地覆盖",
            font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["window"],
        ).pack(anchor="w", padx=28, pady=(0, 18))
        content = tk.Frame(window, bg=COLORS["window"])
        content.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        version_card = self._card(content)
        version_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(
            version_card, text="配置版本", font=FONTS["title"],
            fg=COLORS["text"], bg=COLORS["surface"],
        ).pack(anchor="w", padx=18, pady=(16, 10))
        for version in versions:
            box = tk.Frame(
                version_card, bg=COLORS["cyan_dim"] if version.is_runtime else COLORS["surface_hover"]
            )
            box.pack(fill="x", padx=18, pady=5)
            tk.Label(
                box,
                text=f"{version.config_version}  {'● 运行中' if version.is_runtime else ''}",
                font=FONTS["title"],
                fg=COLORS["cyan"] if version.is_runtime else COLORS["text"],
                bg=box["bg"],
            ).pack(anchor="w", padx=12, pady=(9, 2))
            tk.Label(
                box, text=f"{version.status} · {version.effective_at}",
                font=FONTS["small"], fg=COLORS["muted"], bg=box["bg"],
            ).pack(anchor="w", padx=12)
            for key, value in version.parameters:
                tk.Label(
                    box, text=f"{key}：{value}", font=FONTS["small"],
                    fg=COLORS["text"], bg=box["bg"],
                ).pack(anchor="w", padx=12, pady=(2, 0))
            tk.Frame(box, bg=box["bg"], height=8).pack()
        state_card = self._card(content)
        state_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(
            state_card, text="回撤档位", font=FONTS["title"],
            fg=COLORS["text"], bg=COLORS["surface"],
        ).pack(anchor="w", padx=18, pady=(16, 10))
        for level in levels:
            row = tk.Frame(state_card, bg=COLORS["surface"])
            row.pack(fill="x", padx=18, pady=5)
            tk.Label(
                row, text=f"{level.asset_id} · {level.level_id}",
                font=FONTS["mono"], fg=COLORS["text"], bg=COLORS["surface"],
            ).pack(side="left")
            color = (
                COLORS["green"] if level.status == "FILLED"
                else COLORS["yellow"] if level.status in {"TRIGGERED", "PARTIALLY_FILLED"}
                else COLORS["muted"]
            )
            tk.Label(
                row,
                text=f"{level.status}  ¥{level.filled_cny:,.0f}",
                font=FONTS["small"], fg=color, bg=COLORS["surface"],
            ).pack(side="right")


def default_database_path() -> Path:
    configured = os.environ.get("TRADE_HELPER_DB")
    if configured:
        return Path(configured).expanduser()
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError(
                "Windows LOCALAPPDATA is unavailable; set TRADE_HELPER_DB"
            )
        return Path(local_app_data) / "TradeHelper" / "account.db"
    return Path("var/account.db")


def main() -> int:
    database = default_database_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    app = TradeHelperApp(DashboardRepository(database).load(), database)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
