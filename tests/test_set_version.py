import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("set_version", Path(__file__).resolve().parent.parent / "scripts" / "set_version.py")
sv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sv)


@pytest.mark.parametrize("tag,ver", [
    ("v0.6.2", "0.6.2"), ("v.0.6.1", "0.6.1"), ("0.7.0", "0.7.0"), ("refs/tags/v1.0.0", "1.0.0"),
    ("v1.2", "1.2"), ("v1.0.0-rc1", "1.0.0-rc1"),
])
def test_parse_tag(tag, ver):
    assert sv.parse_tag(tag) == ver


@pytest.mark.parametrize("tag", ["", "vfoo", "release", "v", "v1"])
def test_parse_tag_bad(tag):
    with pytest.raises(ValueError):
        sv.parse_tag(tag)


def test_stamp(tmp_path):
    f = tmp_path / "__init__.py"
    f.write_bytes(b'"""doc"""\n__version__ = "0.3.0"\nAUTHOR = "x"\n')
    sv.stamp("0.6.2", f)
    assert f.read_bytes() == b'"""doc"""\n__version__ = "0.6.2"\nAUTHOR = "x"\n'
    f.write_bytes(b"nothing here\n")
    with pytest.raises(RuntimeError):
        sv.stamp("1.0.0", f)
