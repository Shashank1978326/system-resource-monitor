"""Use an isolated application data directory for every test run."""

import os
import shutil
import tempfile
from pathlib import Path

_tests_root = Path(__file__).resolve().parent
_temp_root = _tests_root / ".test_tmp"
_temp_root.mkdir(parents=True, exist_ok=True)

_mpl_cache_directory = os.path.join(str(_temp_root), "system-resource-monitor-mpl-cache")
try:
    os.makedirs(_mpl_cache_directory, exist_ok=True)
except OSError:
    pass
os.environ.setdefault("MPLCONFIGDIR", _mpl_cache_directory)

_original_app_data_dir = os.environ.get("APP_DATA_DIR")
_test_data_directory = tempfile.TemporaryDirectory(
    dir=str(_temp_root), prefix="system-resource-monitor-tests-"
)
os.environ["APP_DATA_DIR"] = _test_data_directory.name


def pytest_unconfigure(config) -> None:
    if _original_app_data_dir is None:
        os.environ.pop("APP_DATA_DIR", None)
    else:
        os.environ["APP_DATA_DIR"] = _original_app_data_dir
    try:
        from app.database.connection import database
        database.dispose()
    except Exception:
        pass
    try:
        _test_data_directory.cleanup()
    except Exception:
        pass
    try:
        if _temp_root.exists():
            shutil.rmtree(str(_temp_root), ignore_errors=True)
    except Exception:
        pass
