"""autostart 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, _update, core


def _backend():
    if sys.platform != "win32":
        print("这个工具只能读写 Windows 的启动项。", file=sys.stderr)
        return None
    try:
        return core.WinRegistry()
    except OSError as e:
        print(f"打不开注册表：{e}", file=sys.stderr)
        return None


def _pick(entries: list[core.Entry], name: str) -> core.Entry | None:
    """按名字找启动项：先精确，再唯一子串。"""
    exact = [e for e in entries if e.name == name]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        print(f"有多条同名的启动项，请用 --source 区分：", file=sys.stderr)
        for e in exact:
            print(f"  {e.name}  ({e.location})", file=sys.stderr)
        return None

    fuzzy = [e for e in entries if name.lower() in e.name.lower()]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if not fuzzy:
        print(f"没找到名字包含「{name}」的启动项", file=sys.stderr)
    else:
        print(f"「{name}」匹配到多条，写全一点：", file=sys.stderr)
        for e in fuzzy:
            print(f"  {e.name}  ({e.location})", file=sys.stderr)
    return None


def cmd_list(args, registry) -> int:
    entries = core.collect(registry, include_all_users=not args.user_only)
    if args.json:
        payload = [{"name": e.name, "command": e.command,
                    "source": e.source, "location": e.location} for e in entries]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("没有开机启动项。")
        return 0

    width = min(max((len(e.name) for e in entries), default=4) + 2, 28)
    print(f"{'名称':<{width}} {'位置':<24} 命令")
    print("-" * (width + 24 + 30))
    for e in entries:
        cmd = e.command if len(e.command) <= 60 else e.command[:57] + "…"
        print(f"{e.name:<{width}} {e.location:<24} {cmd}")
    print(f"\n共 {len(entries)} 条。禁用：autostart disable \"名称\" --yes")
    return 0


def cmd_backup(args, registry) -> int:
    entries = core.collect(registry, include_all_users=True)
    out = Path(args.out) if args.out else None
    path = core.save_backup(entries, out)
    print(f"已备份 {len(entries)} 条启动项 → {path}")
    return 0


def cmd_disable(args, registry) -> int:
    entries = core.collect(registry, include_all_users=not args.user_only)
    entry = _pick(entries, args.name)
    if not entry:
        return 2

    if not args.yes:
        print("即将禁用：")
        print(f"  名称  {entry.name}")
        print(f"  位置  {entry.location}")
        print(f"  命令  {entry.command}")
        print("\n原值会先备份到 %APPDATA%\\autostart-tool\\backups\\，可随时 restore。")
        print("确认无误请加 --yes 重新执行。")
        return 2

    print(core.disable(entry, registry, all_users_ok=args.all_users))
    return 0


def cmd_restore(args, registry) -> int:
    path = Path(args.file) if args.file else core.newest_backup()
    if not path:
        print("没有找到任何备份文件", file=sys.stderr)
        return 2
    if not path.exists():
        print(f"备份文件不存在：{path}", file=sys.stderr)
        return 2

    entries = core.load_backup(path)
    if not args.yes:
        print(f"将从 {path} 恢复 {len(entries)} 条：")
        for e in entries:
            print(f"  {e.name:<24} {e.location}")
        print("\n加 --yes 确认执行。")
        return 2

    for e in entries:
        print(f"  {e.name}: {core.enable(e, registry, all_users_ok=args.all_users)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autostart",
        description="查看和管理 Windows 开机启动项。所有写操作前都会自动备份。",
        epilog='例子：autostart disable "迅雷" --yes',
    )
    p.add_argument("-V", "--version", action="version", version=f"autostart {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="列出启动项")
    ls.add_argument("--json", action="store_true", help="输出 JSON")
    ls.add_argument("--user-only", action="store_true", help="只看当前用户的")

    bk = sub.add_parser("backup", help="把当前启动项全部备份成 JSON")
    bk.add_argument("-o", "--out", help="备份文件路径")

    dis = sub.add_parser("disable", help="禁用一个启动项")
    dis.add_argument("name", help="启动项名称（支持子串匹配）")
    dis.add_argument("--yes", action="store_true", help="真的执行（不加只预览）")
    dis.add_argument("--all-users", action="store_true", help="允许修改 HKLM（需要管理员）")
    dis.add_argument("--user-only", action="store_true", help="只在当前用户的启动项里找")

    rs = sub.add_parser("restore", help="从备份恢复")
    rs.add_argument("file", nargs="?", help="备份文件，默认用最新的一个")
    rs.add_argument("--yes", action="store_true", help="真的执行")
    rs.add_argument("--all-users", action="store_true", help="允许写 HKLM（需要管理员）")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    registry = _backend()
    if registry is None:
        return 2

    handlers = {
        "list": cmd_list,
        "backup": cmd_backup,
        "disable": cmd_disable,
        "restore": cmd_restore,
    }
    try:
        return handlers[args.cmd](args, registry)
    except PermissionError:
        print("权限不足，试着用管理员身份运行。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
