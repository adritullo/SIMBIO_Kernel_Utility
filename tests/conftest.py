import sys
from pathlib import Path

import pytest

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
