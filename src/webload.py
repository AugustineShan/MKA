"""webload.py - package a /load vintage sandbox for Claude.ai.

Output directory: companies/{company}/WEBCLAUDE/模型装载部分/

The packer first runs ``src.model_load.prepare`` to lock the workbook time
boundary and build a load sandbox, then copies only browser-side safe materials
and the required skill documents for /load discussion.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from src.company_paths import webclaude_dir as company_webclaude_dir
from src.model_load import ModelLoadError, prepare_load, resolve_company


BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
CLAUDE_SKILLS_DIR = BASE_DIR / ".claude" / "skills"
WEBLOAD_SUBDIR = "模型装载部分"
MERGED_WEBLOAD_FILE = "00_LOAD网页端合并执行包.md"


def newest_versioned_file(pattern: str, directory: Path = SKILLS_DIR) -> Path | None:
    if not directory.exists():
        return None
    files = list(directory.glob(pattern))
    if not files:
        return None

    def _version(path: Path) -> int:
        match = re.search(r"v(\d+)", path.name)
        return int(match.group(1)) if match else 0

    return max(files, key=_version)


def _copy_tree(src: Path, dest: Path, report: dict[str, str], key: str) -> None:
    if not src.exists():
        report[key] = "SKIP missing"
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    count = sum(1 for path in dest.rglob("*") if path.is_file())
    report[key] = f"OK {count} files"


def _required_versioned_file(pattern: str, label: str) -> Path:
    path = newest_versioned_file(pattern)
    if path is None:
        raise FileNotFoundError(f"missing {label}: {pattern}")
    return path


def _read_required_text(src: Path, label: str) -> str:
    if not src.exists():
        raise FileNotFoundError(f"missing {label}: {src}")
    return src.read_text(encoding="utf-8")


def _append_source_section(parts: list[str], title: str, src: Path, body: str) -> None:
    parts.append(
        "\n\n---\n\n"
        f"## {title}\n\n"
        f"来源：`{src}`\n\n"
        f"{body.strip()}\n"
    )


def _write_merged_webload_markdown(
    package_dir: Path,
    manifest: dict[str, Any],
    *,
    core_discipline: Path,
    source_language: Path,
    loader_skill: Path,
) -> list[dict[str, str]]:
    boundary = manifest["boundary"]
    load_dir = Path(manifest["load_dir"])
    core_assumption_path = Path(manifest["core_assumption_path"])
    root_core_assumption_path = Path(manifest.get("root_core_assumption_path", core_assumption_path))
    load_skill = CLAUDE_SKILLS_DIR / "load" / "SKILL.md"
    boundary_md = load_dir / "model_boundary.md"
    boundary_json = load_dir / "model_boundary.json"
    forbidden = load_dir / "forbidden_materials.md"
    core_assumption = core_assumption_path

    embedded_sources = [
        {"role": "核心纪律", "path": str(core_discipline)},
        {"role": "核心假设源语言", "path": str(source_language)},
        {"role": "load 启动器摘要", "path": str(load_skill)},
        {"role": "model_boundary.md", "path": str(boundary_md)},
        {"role": "model_boundary.json", "path": str(boundary_json)},
        {"role": "forbidden_materials.md", "path": str(forbidden)},
        {"role": "核心假设脚手架", "path": str(core_assumption)},
        {"role": "模型装载器", "path": str(loader_skill)},
    ]

    parts = [
        f"""# LOAD 网页端合并执行包

你现在要在网页端执行 `/load`，不是 `/ka`。

本文件已经由 `/webload` 预合并。网页端只需要读取：

1. 本文件：`{MERGED_WEBLOAD_FILE}`
2. `allowed_materials/` 下的允许材料，尤其是 Excel 模型

不要再寻找或要求读取单独的 `核心纪律`、`核心假设源语言`、`load` 启动器、`model_boundary.*`、`forbidden_materials.md`、模型装载器 skill、`load_manifest.json`、`defaults.yaml`。这些要么已经内嵌在本文，要么只供本地后续编译使用。

## 本次任务

- 目标：把外部 Excel 模型保存为 load-vintage 的 `/comp` 源语言核心假设。
- 输出文件名：`{core_assumption_path.name}`
- 主产物回填路径：`{root_core_assumption_path}`
- 沙箱副本同步路径：`{core_assumption_path}`
- 先给用户完整 overview，讲清你对模型公式层、业务线、毛利/成本、费用、below-OP 与税、利润表预测期边界的理解。
- overview 和逐段确认必须用会议 memo 风格：先讲你的理解、预测、关键旋钮和风险，再等用户确认；不要机械倾倒单元格、完整 markdown、所有 source range 或逐条 knobs。
- 用户确认前，不要补完核心假设、不要编译 yaml1、不要跑 DCF。
- 用户确认后，按时间轴 -> 收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 利润表预测期边界逐段先押再问。
- 每段聊天里只给结论、紧凑表格和待拍板点；完整 `/comp` 源语言、历史原子、source range 和 `knobs` 块写进 `{core_assumption_path.name}`。
- 末尾必须带 `knobs` 机器自报清单代码块。

## 本次边界

- load_dir: `{load_dir}`
- model_path: `{manifest["model_path"]}`
- history_end_year: `{boundary["history_end_year"]}`
- forecast_start_year: `{boundary["forecast_start_year"]}`
- forecast_years: `{boundary["forecast_years"]}`

## 运行纪律摘要

- 这是 load-vintage 模式，目标是保存原模型，不是更新到当前事实。
- 模型公式层/模型时间标签 > 模型内文字说明 > allowed_materials 内材料 > 背景口径。
- 后来的真实业绩不是纠错材料；不能把后验事实写进模型预测。
- 只读 `allowed_materials/`，不要读取禁读清单里的材料正文。
- 若 Excel 有 `年度和半年度` sheet，默认只看这个利润表主视图；不要继续打开或导出 `Model-BS` / `DCF` 表里的 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等驱动因素。
- data_cutoff.db 不打包到网页端；它留在本地 load 沙箱，供后续本地编译和 DCF 使用。
- 公司根目录旧正式核心假设、正式 `Agent/forecast/`、正式 `Agent/data.db` 都不是本次网页端阅读材料。

## 本地后续动作

网页端生成 `{core_assumption_path.name}` 后，把它放回：

```text
{root_core_assumption_path}
```

并同步一份完全相同的副本到：

```text
{core_assumption_path}
```

根目录主产物供 `/ka` 读取；沙箱副本供本地继续编译 `yaml1_load_*.yaml` 并运行：

```bash
py -m src.model_load dcf --load-dir "{load_dir}" --yaml1 "<yaml1_load_path>"
```
"""
    ]

    _append_source_section(
        parts,
        "核心纪律 A：必须完整遵守",
        core_discipline,
        _read_required_text(core_discipline, "核心纪律"),
    )
    _append_source_section(
        parts,
        "核心假设源语言 B：输出语法",
        source_language,
        _read_required_text(source_language, "核心假设源语言"),
    )
    _append_source_section(
        parts,
        "load 启动器：/load 入口、overview 确认门与边界",
        load_skill,
        _read_required_text(load_skill, "load 启动器"),
    )
    _append_source_section(
        parts,
        "模型边界 Markdown：时间轴第零件事",
        boundary_md,
        _read_required_text(boundary_md, "model_boundary.md"),
    )
    _append_source_section(
        parts,
        "模型边界 JSON：精确边界数据",
        boundary_json,
        "```json\n" + _read_required_text(boundary_json, "model_boundary.json").strip() + "\n```",
    )
    _append_source_section(
        parts,
        "禁读清单：只能作为边界，不得打开正文",
        forbidden,
        _read_required_text(forbidden, "forbidden_materials.md"),
    )
    _append_source_section(
        parts,
        "模型装载器：/load 独有读法",
        loader_skill,
        _read_required_text(loader_skill, "模型装载器"),
    )
    _append_source_section(
        parts,
        "核心假设脚手架：按这个文件名和结构输出",
        core_assumption,
        _read_required_text(core_assumption, "核心假设脚手架"),
    )

    (package_dir / MERGED_WEBLOAD_FILE).write_text("\n".join(parts), encoding="utf-8")
    return embedded_sources


def copy_to_webload(
    company: str | Path,
    *,
    model_path: str | Path | None = None,
    load_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    company_dir = resolve_company(company)
    manifest = prepare_load(company_dir, model_path=model_path, load_id=load_id, overwrite=overwrite)
    load_dir = Path(manifest["load_dir"])

    package_dir = company_webclaude_dir(company_dir) / WEBLOAD_SUBDIR
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    report: dict[str, str] = {}
    core_discipline = _required_versioned_file("核心纪律_skill_v*.md", "核心纪律")
    source_language = _required_versioned_file("核心假设源语言_skill_v*.md", "核心假设源语言")
    loader_skill = _required_versioned_file("模型装载器_skill_v*.md", "模型装载器")
    embedded_sources = _write_merged_webload_markdown(
        package_dir,
        manifest,
        core_discipline=core_discipline,
        source_language=source_language,
        loader_skill=loader_skill,
    )
    report["合并执行包"] = f"OK {MERGED_WEBLOAD_FILE}"

    _copy_tree(load_dir / "allowed_materials", package_dir / "allowed_materials", report, "allowed_materials")

    core_assumption_path = Path(manifest["core_assumption_path"])
    package_manifest = {
        "mode": "webload",
        "package_dir": str(package_dir),
        "source_load_manifest": manifest,
        "merged_markdown": MERGED_WEBLOAD_FILE,
        "embedded_sources": embedded_sources,
        "report": report,
        "package_contract": {
            "include": [
                MERGED_WEBLOAD_FILE,
                "allowed_materials/",
                "webload_manifest.json",
            ],
            "embedded_in_merged_markdown": [
                "核心纪律_skill_v*.md",
                "核心假设源语言_skill_v*.md",
                "load 启动器运行摘要",
                "model_boundary.md",
                "model_boundary.json",
                "forbidden_materials.md",
                f"{core_assumption_path.name}",
                "模型装载器_skill_v*.md",
            ],
            "exclude": [
                "data_cutoff.db",
                "load_manifest.json",
                "defaults.yaml",
                "单独的 01-10 阅读件",
                "forbidden materials正文",
                "公司根目录旧正式核心假设",
                "Agent/forecast/",
            ],
        },
    }
    (package_dir / "webload_manifest.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return package_manifest


def build_report(package: dict[str, Any]) -> str:
    manifest = package["source_load_manifest"]
    boundary = manifest["boundary"]
    lines = [
        "=" * 64,
        "  WEBLOAD 打包报告",
        "=" * 64,
        f"  load sandbox : {manifest['load_dir']}",
        f"  model        : {manifest['model_path']}",
        f"  history end  : {boundary['history_end_year']}",
        f"  forecast from: {boundary['forecast_start_year']}",
        f"  package dir  : {package['package_dir']}",
        "-" * 64,
    ]
    for key, status in package["report"].items():
        lines.append(f"  {key:<20}: {status}")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="打包 /load vintage 沙箱到 WEBCLAUDE/模型装载部分/")
    parser.add_argument("company", help="公司名 / 裸代码 / 完整 ticker / 公司目录")
    parser.add_argument("--model", help="显式指定 Excel 模型路径")
    parser.add_argument("--load-id", help="显式指定 Agent/Load/<load_id>")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名 load 沙箱")
    parser.add_argument("--json", action="store_true", help="输出 JSON manifest")
    args = parser.parse_args(argv)

    try:
        package = copy_to_webload(
            args.company,
            model_path=args.model,
            load_id=args.load_id,
            overwrite=args.overwrite,
        )
    except ModelLoadError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: webload package failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(package, ensure_ascii=False, indent=2))
    else:
        print("\n" + build_report(package))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
