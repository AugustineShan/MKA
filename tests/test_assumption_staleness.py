from __future__ import annotations

from pathlib import Path

from src.assumption_staleness import forecast_start_from_core_md, latest_core_assumption_path


def test_forecast_start_from_core_md_reads_knobs_horizon(tmp_path: Path):
    core_md = tmp_path / "公司-核心假设.md"
    core_md.write_text(
        """
# 公司核心假设

历史 2014-2024，显式期 2025-2028。

```yaml
knobs:
  horizon: [2025, 2026, 2027, 2028]
```
""",
        encoding="utf-8",
    )

    source = forecast_start_from_core_md(core_md)

    assert source is not None
    assert source.forecast_start == 2025


def test_latest_core_assumption_prefers_official_and_excludes_reference_candidates(tmp_path: Path):
    official = tmp_path / "公司-20260625-核心假设.md"
    official.write_text("状态: official\n", encoding="utf-8")
    reference = tmp_path / "核心假设参考.md"
    reference.write_text("状态: reference\n", encoding="utf-8")
    load = tmp_path / "模型_核心假设_load20260625.md"
    load.write_text("状态: model-extracted\n", encoding="utf-8")
    brkd = tmp_path / "公司_核心假设_brkd20260625.md"
    brkd.write_text("状态: draft\n", encoding="utf-8")

    for path in [official, reference, load, brkd]:
        path.touch()

    assert latest_core_assumption_path(tmp_path) == official


def test_latest_core_assumption_returns_none_when_only_reference_candidates(tmp_path: Path):
    (tmp_path / "核心假设参考.md").write_text("状态: reference\n", encoding="utf-8")
    (tmp_path / "模型_核心假设_load20260625.md").write_text("状态: model-extracted\n", encoding="utf-8")
    (tmp_path / "公司_核心假设_brkd20260625.md").write_text("状态: draft\n", encoding="utf-8")

    assert latest_core_assumption_path(tmp_path) is None
