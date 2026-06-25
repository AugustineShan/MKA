"""webka.py - 一键打包网页端生成核心假设.md 所需源文件。

输出目录: companies/{公司名}_{代码}/WEBCLAUDE/核心假设部分/
每次执行先清空再复制，防止过时文件污染。
不读取 PDF，年报只打包 Markdown。

CLI:
    python -m src.webka 新乳业
    python -m src.webka 002946
    python -m src.webka 002946.SZ

退出码:
    0  成功
    2  输入无法解析为唯一公司目录
    3  缺少公司判断和最新观点.md
    1  其他 IO 异常
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from src.company_paths import active_vore_dir, annual_reports_dir, webclaude_dir as company_webclaude_dir

BASE_DIR = Path(__file__).resolve().parent.parent
COMPANIES_DIR = BASE_DIR / "companies"
SKILLS_DIR = BASE_DIR / "skills"

TICKER_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
BARE_CODE_RE = re.compile(r"^\d{6}$")


class TickerResolutionError(RuntimeError):
    """输入无法解析为唯一公司目录。"""

    def __init__(self, raw: str, candidates: list[str] | None = None) -> None:
        self.raw = raw
        self.candidates = candidates or []
        super().__init__(f"无法把 {raw!r} 解析为唯一公司目录")


def resolve_company_dir(raw: str) -> Path:
    """把公司名/裸代码/完整 ticker 解析为公司目录 Path。"""
    text = raw.strip()
    upper = text.upper()

    if TICKER_RE.match(upper):
        code = upper.split(".")[0]
        return _find_unique_company(code=code)

    if BARE_CODE_RE.match(text):
        return _find_unique_company(code=text)

    return _find_unique_company(name=text)


def _find_unique_company(
    code: str | None = None, name: str | None = None
) -> Path:
    candidates: list[Path] = []
    if code:
        candidates = sorted(COMPANIES_DIR.glob(f"*_{code}"))
    elif name:
        candidates = sorted(COMPANIES_DIR.glob(f"{name}_*"))

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise TickerResolutionError(name or code or "")
    raise TickerResolutionError(
        name or code or "", candidates=[str(p.name) for p in candidates]
    )


def _guess_ticker_from_dir(company_dir: Path) -> str:
    """从目录名提取 ticker，如 新乳业_002946 -> 002946.SZ。"""
    name = company_dir.name
    if "_" in name:
        code = name.rsplit("_", 1)[-1]
        # 目录名里的代码通常不带后缀，返回裸代码即可
        return code
    return name


def _is_packable_file(path: Path) -> bool:
    if path.name.startswith("~$"):
        return False
    return path.is_file()


def newest_file(dir_path: Path, patterns: list[str]) -> Path | None:
    """取目录下匹配任一模式的最新修改文件。"""
    if not dir_path.exists():
        return None
    files: list[tuple[float, Path]] = []
    for pat in patterns:
        for candidate in dir_path.rglob(pat):
            try:
                if _is_packable_file(candidate):
                    files.append((candidate.stat().st_mtime, candidate))
            except OSError:
                continue
    if not files:
        return None
    return max(files, key=lambda item: item[0])[1]


def newest_annual_report(annuals_dir: Path) -> Path | None:
    """取最新一年年度报告 Markdown。只返回 .md，永远不返回 PDF。"""
    if not annuals_dir.exists():
        return None
    md_files = list(annuals_dir.rglob("*年度报告*.md"))
    if not md_files:
        return None
    # 按文件名降序：最新年份在前；同年份修订版字典序更后，会被优先取到
    md_files.sort(key=lambda p: p.name, reverse=True)
    return md_files[0]


def newest_core_assumption_skill(skills_dir: Path = SKILLS_DIR) -> Path | None:
    """取最新版核心假设生成修改器 skill 文件（按文件名版本号 vN）。"""
    if not skills_dir.exists():
        return None
    files = list(skills_dir.glob("*核心假设生成修改器_skill_v*.md"))
    if not files:
        return None

    def _version(p: Path) -> int:
        m = re.search(r"v(\d+)", p.name)
        return int(m.group(1)) if m else 0

    return max(files, key=_version)


def _has_annual_pdf(annuals_dir: Path) -> bool:
    return bool(list(annuals_dir.rglob("*年度报告*.pdf"))) if annuals_dir.exists() else False


def copy_to_webclaude(company_dir: Path) -> dict[str, str]:
    """清空并重新填充 WEBCLAUDE/核心假设部分/，返回打包报告字典。"""
    webclaude_dir = company_webclaude_dir(company_dir) / "核心假设部分"
    if webclaude_dir.exists():
        shutil.rmtree(webclaude_dir)
    webclaude_dir.mkdir(parents=True)

    report: dict[str, str] = {}

    # 1. 公司判断和最新观点.md（必须）
    core_view = company_dir / "公司判断和最新观点.md"
    if not core_view.exists():
        raise FileNotFoundError(f"缺少公司判断和最新观点.md: {core_view}")
    shutil.copy2(core_view, webclaude_dir / "00_公司判断和最新观点.md")
    report["公司判断和最新观点.md"] = "✅"

    # 2. 现有核心假设底稿（可选，取最新修改）
    core_assumption_files = list(company_dir.glob("*核心假设*.md"))
    if core_assumption_files:
        latest = max(core_assumption_files, key=lambda p: p.stat().st_mtime)
        shutil.copy2(latest, webclaude_dir / "01_核心假设_现有底稿.md")
        report["现有核心假设底稿"] = f"✅ {latest.name}"
    else:
        report["现有核心假设底稿"] = "⏭️ 无（init 模式）"

    # 3. 最新活跃素材（可选）
    active_file = newest_file(active_vore_dir(company_dir), ["*"])
    if active_file:
        dest = webclaude_dir / f"02_活跃素材_{active_file.name}"
        shutil.copy2(active_file, dest)
        report["活跃素材"] = f"✅ {active_file.name}"
    else:
        report["活跃素材"] = "⏭️ 无"

    # 4. 最新年报 Markdown（可选，不读 PDF）
    annuals_dir = annual_reports_dir(company_dir)
    annual_md = newest_annual_report(annuals_dir)
    if annual_md:
        dest = webclaude_dir / f"03_最新年报_{annual_md.name}"
        shutil.copy2(annual_md, dest)
        report["最新年报"] = f"✅ {annual_md.name}"
    else:
        if _has_annual_pdf(annuals_dir):
            report["最新年报"] = "⏭️ 无 Markdown，仅有 PDF（skill 不读 PDF，请先生成年报 Markdown）"
        else:
            report["最新年报"] = "⏭️ 无"

    # 5. 核心假设生成修改器 skill（网页端执行时需要）
    skill_file = newest_core_assumption_skill()
    if skill_file:
        # 源文件已带序号前缀（如 04_），直接沿用原名，避免 04_04_ 重复
        dest = webclaude_dir / skill_file.name
        shutil.copy2(skill_file, dest)
        report["核心假设生成修改器 skill"] = f"✅ {skill_file.name}"
    else:
        report["核心假设生成修改器 skill"] = "⏭️ 无"

    return report


def build_report(company_dir: Path, ticker: str, report: dict[str, str]) -> str:
    lines = [
        "=" * 56,
        f"  WEBCLAUDE 打包报告: {ticker}",
        "=" * 56,
    ]
    for item, status in report.items():
        lines.append(f"  {item:<18} : {status}")
    lines.append("-" * 56)
    lines.append(f"  输出目录: {company_dir / 'WEBCLAUDE' / '核心假设部分'}")
    lines.append("=" * 56)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，报告里的 ✅/❌ 等会崩溃；强制 UTF-8 输出。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="一键打包网页端生成核心假设.md 所需源文件到 WEBCLAUDE/核心假设部分/ 目录"
    )
    parser.add_argument("input", help="公司名 / 裸代码 / 完整 ticker")
    args = parser.parse_args(argv)

    try:
        company_dir = resolve_company_dir(args.input)
    except TickerResolutionError as exc:
        print(f"\n❌ 输入解析失败: {exc}", file=sys.stderr)
        if exc.candidates:
            print("  候选:", file=sys.stderr)
            for c in exc.candidates:
                print(f"    {c}", file=sys.stderr)
        return 2

    ticker = _guess_ticker_from_dir(company_dir)

    try:
        report = copy_to_webclaude(company_dir)
    except FileNotFoundError as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ 打包异常: {exc}", file=sys.stderr)
        return 1

    print("\n" + build_report(company_dir, ticker, report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
