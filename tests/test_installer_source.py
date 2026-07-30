from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class InstallerSourceTests(TestCase):
    def test_required_per_user_and_data_retention_rules_are_present(self) -> None:
        source = (ROOT / "installer" / "TradeHelper.iss").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "DefaultDirName={localappdata}\\Programs\\TradeHelper",
            source,
        )
        self.assertIn("PrivilegesRequired=lowest", source)
        self.assertIn("skipifsilent", source)
        self.assertIn(
            'Source: "{#MyReleaseRoot}\\TradeHelperCLI.exe"',
            source,
        )
        self.assertIn(
            "Intentionally do not remove {localappdata}\\TradeHelper",
            source,
        )
        self.assertIn('Description: "创建桌面快捷方式"', source)
        self.assertIn('Description: "启动 {#MyAppName}"', source)
