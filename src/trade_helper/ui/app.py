from __future__ import annotations

import tkinter as tk
import os
from dataclasses import dataclass
from decimal import Decimal
from tkinter import ttk

from trade_helper.ui.theme import COLORS, FONTS, status_color
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
    def __init__(self, model: DashboardViewModel | None = None) -> None:
        super().__init__()
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
        line = tk.Frame(card, bg=COLORS["cyan_dim"], highlightthickness=1, highlightbackground=COLORS["cyan"])
        line.pack(fill="x", padx=20, pady=18)
        tk.Label(line, text="◇", font=("Segoe UI Symbol", 22), fg=COLORS["cyan"], bg=COLORS["cyan_dim"]).pack(side="left", padx=16, pady=14)
        copy = tk.Frame(line, bg=COLORS["cyan_dim"])
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(copy, text="当前无可执行建议", font=FONTS["title"], fg=COLORS["text"], bg=COLORS["cyan_dim"]).pack(anchor="w")
        tk.Label(copy, text="系统将在数据、对账与风控全部通过后显示建议", font=FONTS["small"], fg=COLORS["muted"], bg=COLORS["cyan_dim"]).pack(anchor="w")
        tk.Button(
            line, text="运行检查", font=FONTS["body"], fg=COLORS["window"],
            bg=COLORS["cyan"], activebackground=COLORS["green"], relief="flat",
            padx=18, pady=8, cursor="hand2",
        ).pack(side="right", padx=16)

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


def main() -> int:
    database = os.environ.get("TRADE_HELPER_DB", "var/account.db")
    app = TradeHelperApp(DashboardRepository(database).load())
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
