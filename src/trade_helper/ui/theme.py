from __future__ import annotations

COLORS = {
    "window": "#F4F5F7",
    "sidebar": "#E9EBEE",
    "surface": "#FFFFFF",
    "surface_hover": "#E0E4E9",
    "border": "#D2D7DD",
    "text": "#2A323C",
    "muted": "#6E7A87",
    "cyan": "#356BB0",
    "cyan_soft": "#D7E3F2",
    "cyan_dim": "#E5EBF4",
    "green": "#2F8F66",
    "yellow": "#B8860B",
    "red": "#C14B4B",
    "blue": "#5F7FA8",
}

FONTS = {
    "hero": ("Microsoft YaHei UI", 19, "bold"),
    "title": ("Microsoft YaHei UI", 13, "bold"),
    "metric": ("Segoe UI", 17, "bold"),
    "body": ("Microsoft YaHei UI", 10),
    "small": ("Microsoft YaHei UI", 9),
    "mono": ("Cascadia Mono", 9),
}


def status_color(status: str) -> str:
    return {
        "READY": COLORS["green"],
        "REVIEW": COLORS["yellow"],
        "BLOCKED": COLORS["red"],
        "RECONCILIATION_REQUIRED": COLORS["red"],
    }.get(status, COLORS["muted"])
