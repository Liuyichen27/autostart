"""autostart 测试。

关键约束：绝不能在测试里动真实的注册表和启动文件夹。
所以全部走 MemoryRegistry + 把 APPDATA / ProgramData 指到临时目录。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autostart import cli, core  # noqa: E402


def sandbox_env(td: str) -> dict[str, str]:
    return {"APPDATA": td, "ProgramData": td}


class TestCollect(unittest.TestCase):
    def test_reads_both_hives(self):
        reg = core.MemoryRegistry({
            "hkcu": {"微信": r"C:\Program Files\WeChat\WeChat.exe"},
            "hklm": {"Driver": r"C:\drv.exe"},
        })
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            entries = core.collect(reg)
            names = [e.name for e in entries]
            self.assertIn("微信", names)
            self.assertIn("Driver", names)
            self.assertEqual(len(entries), 2)

    def test_user_only_excludes_hklm(self):
        reg = core.MemoryRegistry({"hkcu": {"A": "a"}, "hklm": {"B": "b"}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            entries = core.collect(reg, include_all_users=False)
            self.assertEqual([e.name for e in entries], ["A"])

    def test_source_and_location_filled(self):
        reg = core.MemoryRegistry({"hkcu": {"X": "x"}, "hklm": {}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            e = core.collect(reg)[0]
            self.assertEqual(e.source, "registry:hkcu")
            self.assertIn("HKCU", e.location)


class TestDisableRegistry(unittest.TestCase):
    def test_disables_hkcu_and_writes_backup(self):
        reg = core.MemoryRegistry({"hkcu": {"迅雷": r"C:\Thunder.exe"}, "hklm": {}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            entry = core.collect(reg, include_all_users=False)[0]
            msg = core.disable(entry, reg)

            self.assertIn("已禁用", msg)
            self.assertIsNone(reg.read_value("hkcu", "迅雷"))
            backups = list((Path(td) / "autostart-tool" / "backups").glob("backup-*.json"))
            self.assertEqual(len(backups), 1)

            restored = core.load_backup(backups[0])
            self.assertEqual(restored[0].command, r"C:\Thunder.exe")

    def test_hklm_requires_all_users_flag(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {"Svc": "svc.exe"}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            entry = core.collect(reg, include_all_users=True)[0]
            msg = core.disable(entry, reg)
            self.assertIn("管理员", msg)
            self.assertEqual(reg.read_value("hklm", "Svc"), "svc.exe")  # 没被动

    def test_all_users_flag_allows_hklm(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {"Svc": "svc.exe"}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            entry = core.collect(reg, include_all_users=True)[0]
            msg = core.disable(entry, reg, all_users_ok=True)
            self.assertIn("已禁用", msg)
            self.assertIsNone(reg.read_value("hklm", "Svc"))

    def test_missing_entry_is_reported(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {}})
        entry = core.Entry("ghost", "x", "registry:hkcu", "HKCU Run")
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            self.assertIn("没找到", core.disable(entry, reg))


class TestStartupFolder(unittest.TestCase):
    def _make_folder_with_item(self, td: str) -> Path:
        folder = core.startup_folder(False)
        folder.mkdir(parents=True, exist_ok=True)
        item = folder / "网易云音乐.lnk"
        item.write_text("fake link", encoding="utf-8")
        return item

    def test_folder_items_are_collected(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            self._make_folder_with_item(td)
            entries = core.collect(reg, include_all_users=False)
            self.assertEqual([e.name for e in entries], ["网易云音乐"])
            self.assertEqual(entries[0].source, "folder:user")

    def test_disable_moves_file_not_deletes(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            item = self._make_folder_with_item(td)
            entry = core.collect(reg, include_all_users=False)[0]

            msg = core.disable(entry, reg)
            self.assertIn("已移到", msg)
            self.assertFalse(item.exists())
            backup_item = core.backup_dir() / "startup-items" / "网易云音乐.lnk"
            self.assertTrue(backup_item.exists(), "文件应该被移走而不是删掉")

    def test_enable_moves_file_back(self):
        reg = core.MemoryRegistry({"hkcu": {}, "hklm": {}})
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            item = self._make_folder_with_item(td)
            entry = core.collect(reg, include_all_users=False)[0]
            core.disable(entry, reg)

            msg = core.enable(entry, reg)
            self.assertIn("已恢复", msg)
            self.assertTrue(item.exists())


class TestBackupRestore(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        entries = [
            core.Entry("A", "a.exe", "registry:hkcu", "HKCU Run"),
            core.Entry("B", "b.lnk", "folder:user", "启动文件夹（当前用户）"),
        ]
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            path = core.save_backup(entries)
            self.assertTrue(path.exists())
            loaded = core.load_backup(path)
            self.assertEqual([e.name for e in loaded], ["A", "B"])
            self.assertEqual(loaded[1].source, "folder:user")

    def test_newest_backup(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            d = core.backup_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / "backup-20200101-000000.json").write_text('{"entries": []}', encoding="utf-8")
            (d / "backup-20991231-000000.json").write_text('{"entries": []}', encoding="utf-8")
            self.assertEqual(core.newest_backup().name, "backup-20991231-000000.json")

    def test_no_backup_returns_none(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, sandbox_env(td)):
            self.assertIsNone(core.newest_backup())


class TestPick(unittest.TestCase):
    def setUp(self):
        self.entries = [
            core.Entry("WeChat", "w.exe", "registry:hkcu", "HKCU Run"),
            core.Entry("WeGame", "g.exe", "registry:hkcu", "HKCU Run"),
        ]

    def test_exact_match_wins(self):
        self.assertEqual(cli._pick(self.entries, "WeChat").name, "WeChat")

    def test_unique_substring(self):
        self.assertEqual(cli._pick(self.entries, "chat").name, "WeChat")

    def test_ambiguous_returns_none(self):
        self.assertIsNone(cli._pick(self.entries, "We"))

    def test_not_found_returns_none(self):
        self.assertIsNone(cli._pick(self.entries, "Nothing"))


if __name__ == "__main__":
    unittest.main()
