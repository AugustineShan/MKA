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


def test_gpm_to_ex_dep_identity_at_base():
    from src.forecast import gpm_to_ex_dep
    # gpm_ex_dep = gpm + base_total_dep/revenue
    assert gpm_to_ex_dep(gpm=0.30, base_total_dep=60.0, revenue=1000.0) == pytest.approx(0.36)

def test_ebit_identity_heavy_equals_light_at_base():
    # EBIT_heavy(base) = EBIT_light(base) when da_roll base dep = base_total_dep
    from src.forecast import gpm_to_ex_dep
    revenue = 1000.0
    gpm_light = 0.30
    oper_cost_light = revenue * (1 - gpm_light)          # 700
    base_dep = 60.0
    gpm_ex = gpm_to_ex_dep(gpm_light, base_dep, revenue) # 0.36
    oper_cost_heavy = revenue * (1 - gpm_ex)             # 640
    ebit_light = revenue - oper_cost_light               # 300
    ebit_heavy = revenue - oper_cost_heavy - base_dep    # 1000-640-60=300
    assert ebit_heavy == pytest.approx(ebit_light)