from __future__ import annotations

import os

from src.webka import newest_file


def test_newest_file_skips_office_lock_files(tmp_path):
    real_file = tmp_path / "model.xlsm"
    lock_file = tmp_path / "~$model.xlsm"
    real_file.write_text("real", encoding="utf-8")
    lock_file.write_text("lock", encoding="utf-8")
    os.utime(real_file, (100, 100))
    os.utime(lock_file, (200, 200))

    assert newest_file(tmp_path, ["*"]) == real_file
