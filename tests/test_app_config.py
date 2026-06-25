from __future__ import annotations

from pathlib import Path

from src import app_config


def test_env_writer_preserves_comments_and_masks_secret(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# keep me\n"
        "TUSHARE_TOKEN=old-secret\n"
        "LLM_PROVIDER=glm\n",
        encoding="utf-8",
    )

    app_config.write_env_updates(
        {
            "TUSHARE_TOKEN": "new-secret-value",
            "GLM_MODEL": "glm-5.2",
            "UNKNOWN_KEY": "ignored",
        },
        path=env_path,
    )

    text = env_path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "TUSHARE_TOKEN=new-secret-value" in text
    assert "LLM_PROVIDER=glm" in text
    assert "GLM_MODEL=glm-5.2" in text
    assert "UNKNOWN_KEY" not in text
    assert app_config.masked_secret("new-secret-value") == "****alue"


def test_read_env_values_supports_quoted_windows_paths(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text('MKA_COMPANIES_DIR="D:\\MKA Companies\\companies"\n', encoding="utf-8")

    values = app_config.read_env_values(env_path)

    assert values["MKA_COMPANIES_DIR"] == "D:\\MKA Companies\\companies"


def test_researcher_name_is_exposed_and_writable(tmp_path: Path):
    env_path = tmp_path / ".env"

    app_config.write_env_updates({app_config.RESEARCHER_NAME_KEY: "张三"}, path=env_path)

    assert app_config.get_researcher_name(env_path) == "张三"
    field = next(field for field in app_config.ENV_FIELDS if field.key == app_config.RESEARCHER_NAME_KEY)
    assert field.section == "output"
    assert field.label == "研究员名字"


def test_validate_companies_dir_counts_child_dirs(tmp_path: Path):
    companies = tmp_path / "companies"
    (companies / "测试_000001").mkdir(parents=True)
    (companies / "notes.txt").write_text("x", encoding="utf-8")

    validation = app_config.validate_companies_dir(companies)

    assert validation["exists"] is True
    assert validation["is_dir"] is True
    assert validation["company_count"] == 1


def test_rating_report_year_config_defaults_and_sanitizes_ranges(tmp_path: Path, monkeypatch):
    for key in app_config.RATING_REPORT_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    env_path = tmp_path / ".env"

    assert app_config.rating_report_year_config(env_path) == {
        "data_start_year": 2023,
        "data_end_year": 2025,
        "forecast_start_year": 2026,
        "forecast_end_year": 2028,
    }

    env_path.write_text(
        "MKA_RATING_REPORT_DATA_START_YEAR=2024\n"
        "MKA_RATING_REPORT_DATA_END_YEAR=2023\n"
        "MKA_RATING_REPORT_FORECAST_START_YEAR=2029\n"
        "MKA_RATING_REPORT_FORECAST_END_YEAR=bad\n",
        encoding="utf-8",
    )

    assert app_config.rating_report_year_config(env_path) == {
        "data_start_year": 2024,
        "data_end_year": 2024,
        "forecast_start_year": 2029,
        "forecast_end_year": 2029,
    }
