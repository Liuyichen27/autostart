# autostart · Windows 开机启动项管理

[![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6)](#)
[![License](https://img.shields.io/badge/license-MIT-12B76A)](LICENSE)

看清楚开机时到底有什么在偷偷启动，不想要的一条命令禁掉——**改之前自动备份，随时能还原**。

```bash
autostart list
autostart disable "迅雷" --yes
```

## 为什么不用任务管理器

任务管理器的「启动」页只显示一部分东西，而且：

- 看不到 HKLM 和启动文件夹的完整情况（它合并显示，路径信息还被截断）
- 禁用了不会告诉你原理，想恢复时找不到在哪
- 命令行里没法用，更没法写脚本

`autostart` 把三个真实来源摊开给你看，每条都带完整命令和来源位置。

## 安装

```bash
pip install git+https://github.com/Liuyichen27/autostart.git
```

零依赖，纯标准库（`winreg`），只支持 Windows。

## 三个来源

| 来源 | 位置 | 提权 |
| --- | --- | --- |
| HKCU Run | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 不需要 |
| HKLM Run | `HKLM\Software\Microsoft\Windows\CurrentVersion\Run` | **需要管理员** |
| 启动文件夹 | `%APPDATA%\...\Start Menu\Programs\Startup` 和 `%ProgramData%\...` | 所有用户的那份要管理员 |

## 用法

### 看

```bash
autostart list              # 全部
autostart list --user-only  # 只看当前用户的
autostart list --json       # 给脚本用
```

```
名称                            位置                    命令
------------------------------------------------------------
Ollama                          启动文件夹（当前用户）    C:\Users\...\Startup\Ollama.lnk
LGHUB                           HKCU Run（当前用户）      "C:\Program Files\LGHUB\...\lghub_system_tray.exe" --minimized
Adguard                         HKLM Run（所有用户）      "C:\Program Files\AdGuard\Adguard.exe" /nosplash

共 21 条。禁用：autostart disable "名称" --yes
```

### 禁用

```bash
autostart disable "迅雷"        # 先预览，什么都不改
autostart disable "迅雷" --yes  # 真的执行
```

不加 `--yes` 只打印「即将禁用什么」，你可以先确认没认错名字。

名称支持**子串匹配**，但如果匹配到多条会拒绝执行并列出候选，不会瞎猜。

**HKLM 的项需要管理员权限**，不加 `--all-users` 会直接告诉你需要提权，而不是静默失败。

### 恢复

```bash
autostart backup                 # 手动存一份当前状态
autostart restore --yes          # 从最新备份恢复
autostart restore 某个备份.json --yes
```

每次 `disable` 也会自动先存备份，所以就算忘了手动备份也能找回来。

备份文件在：

```
%APPDATA%\autostart-tool\backups\backup-20261025-113000.json
```

## 和「删除」的区别

- **注册表项**：先把原值写进 JSON，再从注册表删掉。恢复就是把值写回去
- **启动文件夹项**：文件**移到**备份目录（`backups\startup-items\`），不是删除。恢复就是移回原处

整个工具里没有 `unlink` 调用。最坏情况是文件躺在备份文件夹里，你手动拷回去就行。

## 参数

| 参数 | 说明 |
| --- | --- |
| `list --json` | JSON 输出 |
| `list --user-only` | 只看当前用户 |
| `disable <名称> --yes` | 真执行；不加 `--yes` 只预览 |
| `disable --all-users` | 允许修改 HKLM（需管理员） |
| `restore [文件] --yes` | 从备份恢复，省略文件则用最新的 |

## 作为库调用

```python
from autostart import core

reg = core.WinRegistry()
for e in core.collect(reg, include_all_users=False):
    print(e.name, "->", e.command)
```

`core.MemoryRegistry()` 是内存实现，可以拿来做无副作用的测试。

## 测试

```bash
python -m unittest discover -s tests -v
```

17 个用例，**全部走内存注册表 + 临时目录**，不会碰你真实的启动项：HKLM 提权拦截、备份写入、文件夹项移动而非删除、恢复回原位、同名歧义拒绝执行等。

## 已知限制

- 不检查「计划任务」和「服务」里的自启动（那是另一套机制，误操作风险高）
- 不解析 `.lnk` 的真实指向（需要 COM，为了零依赖没做），只显示 `.lnk` 路径
- 32 位程序写入的 `WOW6432Node` 项没单独列（统一按 64 位视图读）

## 许可

MIT License，详见 [LICENSE](LICENSE)。

---

<sub>English: autostart lists Windows startup entries from HKCU Run, HKLM Run and both Startup folders with their full command lines, and lets you disable them by name. It never deletes anything: registry values are backed up to JSON first, and startup-folder items are *moved* to a backup directory so `restore` can put them back. HKLM changes require the `--all-users` flag and admin rights, and disabling without `--yes` only previews.</sub>
