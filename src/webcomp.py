"""webcomp.py - 一键打包网页端编译 yaml1 所需输入材料。

输出目录: companies/{公司名}_{代码}/WEBCLAUDE/yaml1编译部分/
每次执行先清空再复制，防止过时文件污染。

CLI:
    python -m src.webcomp 新乳业
    python -m src.webcomp 002946
    python -m src.webcomp 002946.SZ

退出码:
    0  成功
    2  输入无法解析为唯一公司目录
    3  缺少核心假设.md 或 defaults.yaml
    1  其他 IO 异常
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
COMPANIES_DIR = BASE_DIR / "companies"
DOCS_DIR = BASE_DIR / "docs"
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
    """从目录名提取代码，如 新乳业_002946 -> 002946。"""
    name = company_dir.name
    if "_" in name:
        return name.rsplit("_", 1)[-1]
    return name


def newest_yaml1compiler_skill(skills_dir: Path = SKILLS_DIR) -> Path | None:
    """取最新版 yaml1compiler skill 文件（按文件名版本号 vN）。"""
    if not skills_dir.exists():
        return None
    files = list(skills_dir.glob("yaml1compiler_v*.md"))
    if not files:
        return None

    def _version(p: Path) -> int:
        m = re.search(r"v(\d+)", p.name)
        return int(m.group(1)) if m else 0

    return max(files, key=_version)


def copy_to_webcomp(company_dir: Path) -> dict[str, str]:
    """清空并重新填充 WEBCLAUDE/yaml1编译部分/，返回打包报告字典。"""
    webcomp_dir = company_dir / "WEBCLAUDE" / "yaml1编译部分"
    if webcomp_dir.exists():
        shutil.rmtree(webcomp_dir)
    webcomp_dir.mkdir(parents=True)

    report: dict[str, str] = {}

    # 1. 核心假设.md（必须）
    core_assumption_files = list(company_dir.glob("*核心假设*.md"))
    if not core_assumption_files:
        raise FileNotFoundError(f"缺少*核心假设*.md: {company_dir / '*核心假设*.md'}")
    latest_core = max(core_assumption_files, key=lambda p: p.stat().st_mtime)
    shutil.copy2(latest_core, webcomp_dir / "00_核心假设.md")
    report["核心假设.md"] = f"✅ {latest_core.name}"

    # 2. defaults.yaml（必须）
    defaults = company_dir / "defaults.yaml"
    if not defaults.exists():
        raise FileNotFoundError(f"缺少 defaults.yaml: {defaults}")
    shutil.copy2(defaults, webcomp_dir / "01_defaults.yaml")
    report["defaults.yaml"] = "✅"

    # 3. docs/数据格式参考.md
    data_format = DOCS_DIR / "数据格式参考.md"
    if data_format.exists():
        shutil.copy2(data_format, webcomp_dir / "02_数据格式参考.md")
        report["数据格式参考.md"] = "✅"
    else:
        report["数据格式参考.md"] = "⏭️ 无"

    # 4. docs/yaml1算法模板契约.md
    contract = DOCS_DIR / "yaml1算法模板契约.md"
    if contract.exists():
        shutil.copy2(contract, webcomp_dir / "03_yaml1算法模板契约.md")
        report["yaml1算法模板契约.md"] = "✅"
    else:
        report["yaml1算法模板契约.md"] = "⏭️ 无"

    # 5. yaml1compiler skill（网页端执行时需要）
    skill_file = newest_yaml1compiler_skill()
    if skill_file:
        dest = webcomp_dir / f"04_{skill_file.name}"
        shutil.copy2(skill_file, dest)
        report["yaml1compiler skill"] = f"✅ {skill_file.name}"
    else:
        report["yaml1compiler skill"] = "⏭️ 无"

    return report


def build_report(company_dir: Path, ticker: str, report: dict[str, str]) -> str:
    lines = [
        "=" * 56,
        f"  WEBCOMP 打包报告: {ticker}",
        "=" * 56,
    ]
    for item, status in report.items():
        lines.append(f"  {item:<22} : {status}")
    lines.append("-" * 56)
    lines.append(f"  输出目录: {company_dir / 'WEBCLAUDE' / 'yaml1编译部分'}")
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
        description="一键打包网页端编译 yaml1 所需输入材料到 WEBCLAUDE/yaml1编译部分/ 目录"
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
        report = copy_to_webcomp(company_dir)
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
