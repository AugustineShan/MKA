"""webka.py - 把 /ka 裁决所需的规则与材料打包成 3 份合并 Markdown 供网页端上传。

输出目录: companies/{公司}/WEBCLAUDE/webka(Claude帮你统摄核心假设）/
  - readme first.md                  入口：任务/读取顺序/输出契约/不能跑脚本
  - 必读和素材.md                     合并：4 份规则 + 最高权重材料 + BRKD/LOAD/reference/旧稿 + defaults.yaml
  - 不必要读强制碰到再速查.md          合并：core_metrics_overview + OfficialBreakdowns（按需才查）

网页端 Claude 跑不了脚本、读不了本地文件系统，所以：
1. 本地先跑 src.ka_prepare，把最高权重材料 markdown 化（网页端读不了 raw PDF/Word）。
2. 强制 /ka §2 门禁（根目录有正式稿且未说 --rebuild → 停）与 §6b 门禁
   （BRKD/LOAD/reference 三者全无 → 停）。
3. 把规则与材料合并成 3 份 md，网页端上传这 3 份即可。
4. 不写 manifest：纯打包，无下游机器消费；打包结果 print 到终端。

CLI:
    python -m src.webka 新乳业
    python -m src.webka 002946
    python -m src.webka 002946.SZ --rebuild

退出码:
    0  成功
    2  公司解析或 ka_prepare 失败
    3  §2 已有正式稿门禁或 §6b 骨架门禁未过
    1  其他 IO 异常
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from src.company_paths import (
    ka_reference_dir,
    official_breakdowns_dir,
    top_weight_markdown_store_dir,
    webclaude_dir,
)
from src.ka_prepare import KaPrepareError, prepare_top_weight_materials, resolve_company

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
DOCS_DIR = BASE_DIR / "docs"

WEBKA_SUBDIR = "webka(Claude帮你统摄核心假设）"
README_NAME = "readme first.md"
MUST_READ_NAME = "必读和素材.md"
LOOKUP_NAME = "不必要读强制碰到再速查.md"

# 根目录 *核心假设*.md 里，这些后缀属于 load/brkd/alphapai/参考 候选，不算正式稿
NON_OFFICIAL_TAGS = ("_核心假设_load", "_核心假设_brkd", "_核心假设_alphapai", "核心假设参考")


class WebkaGateError(RuntimeError):
    """§2 已有正式稿门禁或 §6b 骨架门禁未过。"""


def newest_versioned_file(pattern: str, directory: Path = SKILLS_DIR) -> Path | None:
    files = list(directory.glob(pattern))
    if not files:
        return None

    def _version(path: Path) -> int:
        match = re.search(r"v(\d+)", path.name)
        return int(match.group(1)) if match else 0

    return max(files, key=_version)


def _read_text(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"缺少 {label}: {path}")
    return path.read_text(encoding="utf-8")


def _official_drafts(company_dir: Path) -> list[Path]:
    """根目录 *核心假设*.md，剔除 load/brkd/alphapai/参考 候选，剩下的视为正式稿。"""
    out: list[Path] = []
    for path in sorted(company_dir.glob("*核心假设*.md")):
        if any(tag in path.name for tag in NON_OFFICIAL_TAGS):
            continue
        out.append(path)
    return out


def _valid_load_drafts(company_dir: Path) -> list[Path]:
    """§6 门禁：KA 参考稿区的 核心假设参考load_*.md，须有 knobs 块、不得仍是「待模型装载器补全」脚手架。"""
    ka_dir = ka_reference_dir(company_dir)
    if not ka_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(ka_dir.glob("核心假设参考load_*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "待模型装载器补全" in text:
            continue
        if "```knobs" not in text:
            continue
        out.append(path)
    return out


def _reference_candidates(company_dir: Path) -> list[Path]:
    """§6b：KA 参考稿区的 核心假设参考*.md，剔除 LOAD（§6 单独计数）。"""
    ka_dir = ka_reference_dir(company_dir)
    if not ka_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(ka_dir.glob("核心假设参考*.md")):
        if path.name.startswith("核心假设参考load_"):
            continue
        out.append(path)
    return out


def _check_gates(company_dir: Path, *, rebuild: bool) -> dict[str, object]:
    """跑 §2 / §6b 门禁，返回拉起的候选材料。"""
    officials = _official_drafts(company_dir)
    if officials and not rebuild:
        names = "、".join(p.name for p in officials)
        raise WebkaGateError(
            f"公司根目录已有正式核心假设稿（{names}）。/webka 现在不做 modify。\n"
            "小旋钮走 /frontend-edit 或 /adj quick；边际信息走 /adj incremental；"
            "年报滚动走 /annual-update。\n"
            "若要用新最高权重材料/BRKD/LOAD 全量替换旧稿，请加 --rebuild。"
        )

    brkd = company_dir / "Agent业务讨论.md"
    brkd_ok = brkd.exists()
    loads = _valid_load_drafts(company_dir)
    refs = _reference_candidates(company_dir)
    if not (brkd_ok or loads or refs):
        raise WebkaGateError(
            "没有 BRKD 产物 Agent业务讨论.md、没有已完成 LOAD 产物、也没有 root reference 候选"
            "（如 Alphapai 核心假设参考.md）。/ka 不能凭空生成。\n"
            "建议先跑 /brkd、补完 /load，或放入 Alphapai-load reference 后再回来。"
        )
    return {
        "officials": officials,
        "brkd": brkd if brkd_ok else None,
        "loads": loads,
        "refs": refs,
    }


def _append_section(parts: list[str], title: str, source: str, body: str) -> None:
    parts.append(f"\n\n---\n\n## {title}\n\n来源：`{source}`\n\n{body.strip()}\n")


def _append_optional_file(
    parts: list[str], title: str, path: Path, report: list[tuple[str, str]]
) -> None:
    if not path or not path.exists():
        report.append((title, "SKIP 不存在"))
        return
    _append_section(parts, title, str(path), _read_text(path, title))
    report.append((title, f"OK {path.name}"))


def _build_must_read(
    company_dir: Path, gates: dict[str, object], report: list[tuple[str, str]]
) -> str:
    parts = [
        "# 必读和素材（/ka 网页端合并包）\n\n"
        "本文件已由 `/webka` 预合并，按读取顺序排列：先 4 份规则，再裁决材料。\n"
        "裁决流程在下方「核心假设编辑器 runbook」节（§1-§10），押→拍板→落盘，七段停。\n"
        "范围边界、分红率强制检测、family 硬规则等细节均见该 runbook，本头部不复述。"
    ]

    # 1. 四份规则（必读·规则层）
    core_discipline = newest_versioned_file("核心纪律_skill_v*.md")
    source_language = newest_versioned_file("核心假设源语言_skill_v*.md")
    editor = newest_versioned_file("核心假设编辑器_skill_v*.md")
    knobs_contract = DOCS_DIR / "knobs块契约.md"
    for label, path in (
        ("核心纪律 A（A0-A7 横切纪律）", core_discipline),
        ("核心假设源语言 B（块语法 + §B4 family 硬规则）", source_language),
        ("knobs 块契约（末尾 knobs 机器自报清单真源）", knobs_contract),
        ("核心假设编辑器 runbook（裁决流程 §1-§10）", editor),
    ):
        if path is None:
            raise FileNotFoundError(f"缺少 {label}")
        _append_section(parts, label, str(path), _read_text(path, label))
        report.append((label, f"OK {path.name}"))

    # 2. 最高权重材料（必读·材料层）
    core_view = company_dir / "公司判断和最新观点.md"
    _append_optional_file(parts, "最高权重材料·公司判断和最新观点", core_view, report)

    markdown_store = top_weight_markdown_store_dir(company_dir)
    if markdown_store.exists():
        md_files = sorted(p for p in markdown_store.glob("*.md"))
        for md in md_files:
            _append_section(parts, f"最高权重材料 markdown·{md.name}", str(md), _read_text(md, md.name))
        report.append(("最高权重材料 markdown存储区", f"OK {len(md_files)} 份"))
    else:
        report.append(("最高权重材料 markdown存储区", "SKIP 未生成（ka_prepare 无输出）"))

    # 3. defaults.yaml（§1.1 必读审计对象）
    defaults = company_dir / "Agent" / "defaults.yaml"
    _append_optional_file(parts, "defaults.yaml（§1.1 审计对象：base_period/关键参数/review_flags/分红率）", defaults, report)

    # 4. 门禁材料（业务骨架来源）
    brkd = gates.get("brkd")
    if brkd:
        _append_section(parts, "BRKD 产物·Agent业务讨论.md", str(brkd), _read_text(brkd, "BRKD"))
        report.append(("BRKD Agent业务讨论.md", f"OK {brkd.name}"))
    else:
        report.append(("BRKD Agent业务讨论.md", "SKIP 不存在"))

    loads = gates.get("loads") or []
    if loads:
        load = loads[-1]  # 取最新
        _append_section(parts, "LOAD 产物（load-vintage，最新一份）", str(load), _read_text(load, "LOAD"))
        report.append(("LOAD 产物", f"OK {load.name}（共 {len(loads)} 份，取最新）"))
    else:
        report.append(("LOAD 产物", "SKIP 无已完成 LOAD"))

    refs = gates.get("refs") or []
    for ref in refs:
        _append_section(parts, f"reference 候选·{ref.name}", str(ref), _read_text(ref, "reference"))
    report.append(("reference 候选", f"OK {len(refs)} 份" if refs else "SKIP 无"))

    # 5. 旧正式稿（重建对照，仅 --rebuild 时）
    officials = gates.get("officials") or []
    if officials:
        old = officials[-1]  # 取最新
        _append_section(parts, "旧正式核心假设稿（重建对照，不逐行 base）", str(old), _read_text(old, "旧正式稿"))
        report.append(("旧正式稿（重建对照）", f"OK {old.name}"))
    else:
        report.append(("旧正式稿（重建对照）", "SKIP 无（init 模式）"))

    return "\n".join(parts) + "\n"


def _build_lookup(company_dir: Path, report: list[tuple[str, str]]) -> str:
    parts = [
        "# 不必要读强制碰到再速查（/ka 网页端合并包）\n\n"
        "本文件是 derived 事实快查，**只在裁决某行拿不准时才翻**，不要通读。\n"
        "未含：financial_expense.yaml（/ka 默认不裁决财费，如需附注构成本地补跑后手动贴）、"
        "年报正文（如需附注 excerpt 手动贴）、data.db（web 无法查 SQLite）。"
    ]

    # 1. core_metrics_overview.md（只取 .md，丢 json/csv）
    metrics_md = company_dir / "Agent" / "core_metrics_overview.md"
    _append_optional_file(parts, "core_metrics_overview.md（利润表事实速览）", metrics_md, report)

    # 2. OfficialBreakdowns（取 .csv，丢 jsonl）
    ob_dir = official_breakdowns_dir(company_dir)
    if ob_dir.exists():
        csv_files = sorted(ob_dir.glob("*.csv"))
        for csv in csv_files:
            body = "```csv\n" + _read_text(csv, csv.name).strip() + "\n```"
            _append_section(parts, f"OfficialBreakdowns·{csv.name}（官方业务拆分口径）", str(csv), body)
        report.append(("OfficialBreakdowns csv", f"OK {len(csv_files)} 份" if csv_files else "SKIP 无 csv"))
    else:
        report.append(("OfficialBreakdowns csv", "SKIP 目录不存在"))

    return "\n".join(parts) + "\n"


def _build_readme(
    company_dir: Path, gates: dict[str, object], sizes: dict[str, int]
) -> str:
    code = company_dir.name.rsplit("_", 1)[-1]
    if code.startswith("6"):
        suffix = "SH"
    elif code.startswith(("0", "3")):
        suffix = "SZ"
    elif code.startswith(("8", "4")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    ticker_full = f"{code}.{suffix}"
    company_name = company_dir.name.rsplit("_", 1)[0]
    skeleton = []
    if gates.get("brkd"):
        skeleton.append("BRKD✅")
    if gates.get("loads"):
        skeleton.append("LOAD✅")
    if gates.get("refs"):
        skeleton.append("reference✅")
    skeleton_str = " / ".join(skeleton) or "无（不应到达此处）"
    rebuild = bool(gates.get("officials"))

    return f"""# readme first（/ka 网页端执行入口）

你现在要在网页端执行 `/ka`：把业务层材料裁决成一份新的正式 `核心假设.md`。这不是 `/load`，也不是旧稿 modify。

## 你能做什么、不能做什么

- **不能跑脚本、不能读写本地文件系统**。裁决所需的规则与材料已经预合并到本包两份 md 里。
- 本包共 3 份 md：本 readme、`必读和素材.md`、`不必要读强制碰到再速查.md`。
- `data.db` 没打包（web 无法查 SQLite）；`financial_expense.yaml` 没打包（/ka 默认不裁决财费）；年报正文没打包（太大，如需附注 excerpt 请用户手动贴）。

## 读取顺序

1. 本 readme（先看完）。
2. `必读和素材.md` **全读**：4 份规则（核心纪律 A / 核心假设源语言 B / knobs 块契约 / 核心假设编辑器 runbook）+ 最高权重材料 + BRKD/LOAD/reference/旧稿 + `defaults.yaml`。
3. `不必要读强制碰到再速查.md` **碰到才查**：`core_metrics_overview` 与 `OfficialBreakdowns`，仅在裁决某行拿不准时翻。

裁决流程在 `必读和素材.md` 里的「核心假设编辑器 runbook」§1-§10：锁时间轴四数 → 开场 overview → 接缝总账 → 骨架门 → 数值门 → 年报查证 → 防静默 → 收口。每段「先押判断 → 等用户拍板 → 拍板才落盘」，按语义区块停，不连写。

## 本地已预检的门禁

- §2 已有正式稿门禁：{'重建模式（旧稿已作为对照并入必读和素材.md）' if rebuild else '通过（根目录无正式稿，init 模式）'}。
- §6b 骨架门禁：通过（{skeleton_str}）。

## 输出契约

产出一份 `{company_name}-YYYYMMDD-核心假设.md`（YYYYMMDD = 今日），须含：

- 抬头：`模式: ka` / `状态: official`（有悬项写 `reference`）/ `历史数据至` / `显式预测期` / `衰减期至` / `衰减交接增速` / `永续增长` / `门槛来源`。
- 业务线块（上挂科目 + compiler family + 历史 + 预测 + 三件套 + 来源与裁决）。
- 末尾 ` ```knobs` 机器自报清单（语法以 knobs 块契约为准，值与正文一字不差）。

范围边界、分红率强制检测、family 硬规则、knobs 语法等细节 → 见 `必读和素材.md` 里对应规则节，本 readme 不复述。

## 带回本地

把网页端产出的 `核心假设.md` 拷回公司根目录后，本地按 /ka 铁律 1 落盘：

```bash
py scripts/ka_archive.py "<旧正式稿完整路径>"   # 重建时先归档旧稿
# 再把网页端稿子 Write 成 companies\\{{公司}}\\{{公司名}}-{{今日YYYYMMDD}}-核心假设.md
py -m src.forecast --ticker {ticker_full}          # 再跑 /comp + DCF
```

## 本包大小

- `必读和素材.md`：{sizes.get('必读和素材.md', 0):,} 字节
- `不必要读强制碰到再速查.md`：{sizes.get('不必要读强制碰到再速查.md', 0):,} 字节
"""


def package_webka(company: str | Path, *, rebuild: bool = False) -> dict[str, object]:
    company_dir = resolve_company(company)

    # 1. 跑 ka_prepare，markdown 化最高权重材料
    try:
        prepare_top_weight_materials(company_dir, force=False)
    except KaPrepareError as exc:
        raise WebkaGateError(f"ka_prepare 失败: {exc}") from exc

    # 2. §2 / §6b 门禁
    gates = _check_gates(company_dir, rebuild=rebuild)

    # 3. 清空重建输出目录
    out_dir = webclaude_dir(company_dir) / WEBKA_SUBDIR
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    report: list[tuple[str, str]] = []

    # 4. 合并三份 md
    must_read = _build_must_read(company_dir, gates, report)
    lookup = _build_lookup(company_dir, report)
    sizes = {
        MUST_READ_NAME: len(must_read.encode("utf-8")),
        LOOKUP_NAME: len(lookup.encode("utf-8")),
    }
    readme = _build_readme(company_dir, gates, sizes)

    (out_dir / README_NAME).write_text(readme, encoding="utf-8")
    (out_dir / MUST_READ_NAME).write_text(must_read, encoding="utf-8")
    (out_dir / LOOKUP_NAME).write_text(lookup, encoding="utf-8")

    return {
        "company_dir": str(company_dir),
        "out_dir": str(out_dir),
        "rebuild": rebuild,
        "gates": {
            "officials": [str(p) for p in (gates.get("officials") or [])],
            "brkd": bool(gates.get("brkd")),
            "loads": len(gates.get("loads") or []),
            "refs": len(gates.get("refs") or []),
        },
        "files": {
            README_NAME: sizes.get(README_NAME, 0) or len(readme.encode("utf-8")),
            MUST_READ_NAME: sizes[MUST_READ_NAME],
            LOOKUP_NAME: sizes[LOOKUP_NAME],
        },
        "report": report,
    }


def build_report(result: dict[str, object]) -> str:
    lines = [
        "=" * 64,
        "  WEBKA 打包报告",
        "=" * 64,
        f"  company dir : {result['company_dir']}",
        f"  output dir  : {result['out_dir']}",
        f"  rebuild     : {result['rebuild']}",
        f"  gates       : brkd={result['gates']['brkd']} "
        f"loads={result['gates']['loads']} refs={result['gates']['refs']}",
        "-" * 64,
    ]
    for name, size in result["files"].items():
        lines.append(f"  {name:<34}: {size:,} bytes")
    lines.append("-" * 64)
    for label, status in result["report"]:
        lines.append(f"  {label:<34}: {status}")
    lines.append("=" * 64)
    lines.append("  上传网页端：把 output dir 下 3 份 md 上传即可（readme first 先读）。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="把 /ka 裁决所需规则与材料打包成 3 份合并 Markdown 到 WEBCLAUDE/webka(...)/"
    )
    parser.add_argument("company", help="公司名 / 裸代码 / 完整 ticker / 公司目录")
    parser.add_argument("--rebuild", action="store_true", help="重建模式：放行 §2 门禁，旧稿作对照并入")
    args = parser.parse_args(argv)

    try:
        result = package_webka(args.company, rebuild=args.rebuild)
    except WebkaGateError as exc:
        print(f"\n❌ 门禁未过: {exc}", file=sys.stderr)
        return 3
    except (FileNotFoundError, KaPrepareError) as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ webka 打包异常: {exc}", file=sys.stderr)
        return 1

    print("\n" + build_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
