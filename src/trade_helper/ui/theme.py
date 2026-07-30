from __future__ import annotations

COLORS = {
    "window": "#071019",
    "sidebar": "#0A1521",
    "surface": "#0E1B28",
    "surface_hover": "#132638",
    "border": "#203548",
    "text": "#E8F2FA",
    "muted": "#8297A8",
    "cyan": "#20D7E5",
    "cyan_dim": "#123A43",
    "green": "#42E6A4",
    "yellow": "#F5C451",
    "red": "#FF667A",
    "blue": "#6297FF",
}

FONTS = {
    "hero": ("Microsoft YaHei UI", 25, "bold"),
    "title": ("Microsoft YaHei UI", 15, "bold"),
    "metric": ("Segoe UI", 20, "bold"),
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
