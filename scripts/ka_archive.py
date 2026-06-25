#!/usr/bin/env python
"""ka_archive.py — /ka modify 模式归档旧核心假设底稿。

把 modify 时作为 base 读进来的旧底稿移动到 companies/{公司}/Agent/KAhistory/，
为根目录腾出位置给本次新生成的底稿。

契约（与 /ka skill 对齐）：
  - 归档文件保留原名（3A）：旧底稿叫什么，KAhistory 里就叫什么。
  - 目标已存在（同日重跑等撞名）时加 -HHMMSS 后缀防覆盖（2A）。
  - tracked 文件用 `git mv` 保历史；untracked / 不在 git 仓库时回退 `mv`。
  - 只移动，不改内容，不改 raw_tushare / data.db。

用法：
  py scripts/ka_archive.py "<旧底稿绝对路径>"

退出码：0 成功；1 文件不存在；2 参数错误。
"""
import sys
import subprocess
import shutil
import datetime
from pathlib import Path


def archive(old_path: Path) -> Path:
    old = old_path.resolve()
    if not old.is_file():
        print(f"ka_archive: ERROR not a file: {old}", file=sys.stderr)
        sys.exit(1)

    # KAhistory = 同公司根目录下的 Agent/KAhistory/
    dest_dir = old.parent / "Agent" / "KAhistory"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 3A: 保留原名；2A: 撞名时加 -HHMMSS 后缀
    dest = dest_dir / old.name
    if dest.exists():
        ts = datetime.datetime.now().strftime("%H%M%S")
        dest = dest_dir / f"{old.stem}-{ts}{old.suffix}"

    # git mv 保历史，失败（untracked/不在仓库）回退 mv。
    # 注意：capture_output + text=True 在 Windows 默认用 GBK 解 git 的中文 stderr
    # 会抛 UnicodeDecodeError，必须显式 encoding='utf-8', errors='replace'。
    action = "mv"
    r = subprocess.run(
        ["git", "mv", str(old), str(dest)],
        cwd=old.parent.parent,  # 公司目录，在 D:\MKA 仓库内即可
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        shutil.move(str(old), str(dest))
    else:
        action = "git mv"

    # 英文-only stdout（项目铁律：中文不走 stdout，避免 Git Bash 乱码）。
    # 文件名是中文，不打印；调用方已知路径，只需确认成败与动作。
    suffix_note = " (collision-suffix)" if dest.name != old.name else ""
    print(f"ka_archive: OK via {action}{suffix_note}")
    return dest


def main(argv):
    if len(argv) != 2:
        print("usage: ka_archive.py <old_draft_path>", file=sys.stderr)
        return 2
    archive(Path(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
