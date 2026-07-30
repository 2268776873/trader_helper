import os
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from trade_helper.ui.app import default_database_path


class DesktopAppPathTests(TestCase):
    def test_development_database_remains_workspace_relative(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "frozen", False, create=True),
        ):
            self.assertEqual(Path("var/account.db"), default_database_path())

    def test_packaged_database_uses_local_application_data(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": r"C:\Users\sample\AppData\Local"},
                clear=True,
            ),
            patch.object(sys, "frozen", True, create=True),
        ):
            self.assertEqual(
                Path(r"C:\Users\sample\AppData\Local")
                / "TradeHelper" / "account.db",
                default_database_path(),
            )

    def test_explicit_database_path_has_priority(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TRADE_HELPER_DB": r"D:\TradeData\account.db",
                    "LOCALAPPDATA": r"C:\Ignored",
                },
                clear=True,
            ),
            patch.object(sys, "frozen", True, create=True),
        ):
            self.assertEqual(
                Path(r"D:\TradeData\account.db"), default_database_path()
            )
