"""Make the src package importable regardless of how pytest is invoked.

Also exposes the frozen company fixture used by the data-coupled tests.

Why a frozen fixture: the forecast / cleaner / financial-expense tests used to
glob the live ``companies/*_002946`` directory, whose ``yaml1`` is recompiled
(date-stamped) and whose ``data.db`` is re-fetched over time.  That coupled the
tests' golden values to mutable, git-ignored runtime data, so any recompile or
data refresh turned the suite red without any code change.  ``tests/fixtures/
company_002946`` is a committed, immutable snapshot (data.db, defaults.yaml,
yaml1, and a synthetic 2025 annual-report note stub) so the tests are
deterministic and decoupled from the live workspace.
"""

import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

FIXTURE_COMPANY_DIR = Path(__file__).resolve().parent / "fixtures" / "company_002946"


def copy_fixture_company(tmp_path: Path) -> Path:
    """Copy the frozen 002946 company snapshot into ``tmp_path/companies/<name>/``.

    Use for tests that write outputs (forecast/, .modelking/, financial_expense.yaml).
    Tests that only read may point directly at ``FIXTURE_COMPANY_DIR``.
    """
    dst = tmp_path / "companies" / FIXTURE_COMPANY_DIR.name
    shutil.copytree(FIXTURE_COMPANY_DIR, dst)
    return dst
