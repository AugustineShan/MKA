"""Integration tests for the /da skill (forecast injection + calc heavy-asset branches)."""

import pathlib
import pytest
from src.company_paths import da_schedule_path, da_history_dir


def test_da_schedule_path(tmp_path: pathlib.Path):
    """Test da_schedule_path returns correct path."""
    cd = tmp_path
    result = da_schedule_path(cd)
    assert result.name == "da_schedule.yaml"


def test_da_history_dir(tmp_path: pathlib.Path):
    """Test da_history_dir returns correct path."""
    cd = tmp_path
    result = da_history_dir(cd)
    assert result.name == "DAhistory"