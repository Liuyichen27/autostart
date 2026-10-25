"""读写开机启动项。

设计上把「注册表」抽象成 Registry 接口，测试时换成内存实现，所以这个包能在
没有 Windows 注册表的机器上跑测试。

安全约定：任何写操作之前先把原值备份成 JSON，写在 %APPDATA%\\autostart-tool\\backups\\
下面。删错了可以 restore 回来。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
HIVES = ("hkcu", "hklm")
HIVE_LABEL = {"hkcu": "当前用户", "hklm": "所有用户"}
HIVE_ADMIN = {"hkcu": False, "hklm": True}


@dataclass
class Entry:
    """一个启动项。"""

    name: str
    command: str
    source: str          # "registry:hkcu" / "folder:user" / "folder:all"
    location: str        # 给人看的：HKCU Run / 启动文件夹（当前用户）

    @property
    def key(self) -> str:
        """备份/恢复时用来定位，同名不同来源要能区分。"""
        return f"{self.source}::{self.name}"


class Registry(Protocol):
    def list_values(self, hive: str) -> list[tuple[str, str]]: ...
    def read_value(self, hive: str, name: str) -> str | None: ...
    def set_value(self, hive: str, name: str, value: str) -> None: ...
    def delete_value(self, hive: str, name: str) -> bool: ...


class WinRegistry:
    """真实的注册表实现，只在 Windows 上能构造。"""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("注册表后端只在 Windows 可用")
        import winreg

        self._w = winreg
        self._hives = {"hkcu": winreg.HKEY_CURRENT_USER,
                       "hklm": winreg.HKEY_LOCAL_MACHINE}

    @property
    def _flags(self) -> int:
        w = self._w
        return w.KEY_READ | w.KEY_WRITE | w.KEY_WOW64_64KEY

    def list_values(self, hive: str) -> list[tuple[str, str]]:
        w = self._w
        try:
            key = w.OpenKey(self._hives[hive], RUN_KEY, 0, w.KEY_READ | w.KEY_WOW64_64KEY)
        except FileNotFoundError:
            return []
        except PermissionError:
            return []
        out: list[tuple[str, str]] = []
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = w.EnumValue(key, i)
                except OSError:
                    break
                out.append((name, str(value)))
                i += 1
        return out

    def read_value(self, hive: str, name: str) -> str | None:
        w = self._w
        try:
            key = w.OpenKey(self._hives[hive], RUN_KEY, 0, w.KEY_READ | w.KEY_WOW64_64KEY)
        except OSError:
            return None
        with key:
            try:
                value, _ = w.QueryValueEx(key, name)
                return str(value)
            except FileNotFoundError:
                return None

    def set_value(self, hive: str, name: str, value: str) -> None:
        w = self._w
        with w.OpenKey(self._hives[hive], RUN_KEY, 0, self._flags) as key:
            w.SetValueEx(key, name, 0, w.REG_SZ, value)

    def delete_value(self, hive: str, name: str) -> bool:
        w = self._w
        try:
            with w.OpenKey(self._hives[hive], RUN_KEY, 0, self._flags) as key:
                w.DeleteValue(key, name)
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False


class MemoryRegistry:
    """内存实现，测试用。结构和真实注册表一致：{hive: {name: value}}。"""

    def __init__(self, data: dict[str, dict[str, str]] | None = None) -> None:
        self.data: dict[str, dict[str, str]] = data or {"hkcu": {}, "hklm": {}}

    def list_values(self, hive: str) -> list[tuple[str, str]]:
        return list(self.data.get(hive, {}).items())

    def read_value(self, hive: str, name: str) -> str | None:
        return self.data.get(hive, {}).get(name)

    def set_value(self, hive: str, name: str, value: str) -> None:
        self.data.setdefault(hive, {})[name] = value

    def delete_value(self, hive: str, name: str) -> bool:
        bucket = self.data.get(hive, {})
        if name in bucket:
            del bucket[name]
            return True
        return False


def startup_folder(all_users: bool = False) -> Path:
    """启动文件夹路径。"""
    if all_users:
        base = os.environ.get("ProgramData", r"C:\ProgramData")
        return Path(base) / "Microsoft/Windows/Start Menu/Programs/Startup"
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData/Roaming")
    return Path(base) / "Microsoft/Windows/Start Menu/Programs/Startup"


def collect(registry: Registry, include_all_users: bool = True) -> list[Entry]:
    """把注册表和启动文件夹里的启动项都收上来。"""
    entries: list[Entry] = []

    hives = ["hkcu", "hklm"] if include_all_users else ["hkcu"]
    for hive in hives:
        for name, value in registry.list_values(hive):
            entries.append(Entry(
                name=name,
                command=value,
                source=f"registry:{hive}",
                location=f"{hive.upper()} Run（{HIVE_LABEL[hive]}）",
            ))

    for all_users in ([False, True] if include_all_users else [False]):
        folder = startup_folder(all_users)
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in (".lnk", ".url", ".exe", ".bat", ".cmd"):
                entries.append(Entry(
                    name=f.stem,
                    command=str(f),
                    source="folder:all" if all_users else "folder:user",
                    location="启动文件夹（所有用户）" if all_users else "启动文件夹（当前用户）",
                ))

    entries.sort(key=lambda e: (e.source, e.name.lower()))
    return entries


def backup_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "autostart-tool" / "backups"


def save_backup(entries: list[Entry], target: Path | None = None) -> Path:
    """把一批启动项写成 JSON 备份。"""
    target = target or (backup_dir() / f"backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "entries": [asdict(e) for e in entries],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


def load_backup(path: str | os.PathLike) -> list[Entry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Entry(**e) for e in data.get("entries", [])]


def disable(entry: Entry, registry: Registry, *, all_users_ok: bool = False) -> str:
    """禁用一条启动项，返回一句人话结果。

    注册表项：先备份原值到 JSON，再删除。
    启动文件夹：把文件移到备份目录，不删除。
    """
    if entry.source.startswith("registry:"):
        hive = entry.source.split(":", 1)[1]
        if HIVE_ADMIN[hive] and not all_users_ok:
            return ("需要管理员权限：HKLM 是「所有用户」的启动项，请用管理员身份重新运行")
        original = registry.read_value(hive, entry.name)
        if original is None:
            return "没找到这条启动项，可能已经被删了"
        save_backup([entry])
        ok = registry.delete_value(hive, entry.name)
        return f"已禁用（原值已备份到 {backup_dir()}）" if ok else "删除失败"

    if entry.source.startswith("folder:"):
        src = Path(entry.command)
        if not src.exists():
            return "启动文件夹里找不到这个文件"
        target_dir = backup_dir() / "startup-items"
        target_dir.mkdir(parents=True, exist_ok=True)
        save_backup([entry])
        shutil.move(str(src), str(target_dir / src.name))
        return f"已移到 {target_dir}"

    return "不认识的来源，什么都没做"


def enable(entry: Entry, registry: Registry, *, all_users_ok: bool = False) -> str:
    """把一条启动项恢复回去。"""
    if entry.source.startswith("registry:"):
        hive = entry.source.split(":", 1)[1]
        if HIVE_ADMIN[hive] and not all_users_ok:
            return "需要管理员权限：HKLM 的启动项要提权才能写"
        registry.set_value(hive, entry.name, entry.command)
        return "已恢复"

    if entry.source.startswith("folder:"):
        name = Path(entry.command).name
        src = backup_dir() / "startup-items" / name
        if not src.exists():
            return f"备份里找不到 {name}，无法恢复"
        dest_dir = startup_folder(entry.source == "folder:all")
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest_dir / name))
        return f"已恢复到 {dest_dir}"

    return "不认识的来源，什么都没做"


def newest_backup() -> Path | None:
    d = backup_dir()
    if not d.is_dir():
        return None
    files = sorted(d.glob("backup-*.json"))
    return files[-1] if files else None
