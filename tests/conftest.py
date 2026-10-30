import os
import sys
import tempfile
from pathlib import Path

import pytest

# never let the tests read/write the real user settings (registry on Windows): fresh ini file per test run
os.environ["SKU_SETTINGS_FILE"] = str(Path(tempfile.mkdtemp(prefix="sku_test_settings_")) / "settings.ini")

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import make_mock_kernels as mock  # noqa: E402
from simbio_utility.core.kernels import KernelSession  # noqa: E402


@pytest.fixture(scope="session")
def session(tmp_path_factory):
    mk = mock.build(tmp_path_factory.mktemp("kernels_root"))
    ks = KernelSession()
    ks.load(mk)
    yield ks
    ks.unload()
