"""Kernel download: metakernel parsing/rewriting + a real FTP transfer against a local pyftpdlib server."""
import shutil
import threading
from pathlib import Path

import pytest

import make_mock_kernels as mock
from simbio_utility.core import download as dl
from simbio_utility.core.errors import UtilityError
from simbio_utility.core.kernels import KernelSession

MK_TEXT = r"""KPL/MK
header text with a fake (assignment) = ( 'ignored' )
\begindata
PATH_VALUES  = ( '/some/old/place' )
PATH_SYMBOLS = ( 'KERNELS' )
KERNELS_TO_LOAD = (
      '$KERNELS/lsk/a.tls',
      '$KERNELS/spk/long_name_that_continues_+'
      'on_next_string.bsp',
      '/absolute/other.bsp'
)
\begintext
trailer
"""


def test_parse_metakernel(tmp_path):
    p = tmp_path / "x.tm"
    p.write_text(MK_TEXT)
    mk = dl.parse_metakernel(p)
    assert [e.rel for e in mk.entries] == ["lsk/a.tls", "spk/long_name_that_continues_on_next_string.bsp"]
    assert mk.skipped == ["/absolute/other.bsp"]
    assert mk.counts_by_folder() == {"lsk": 1, "spk": 1}
    assert mk.values == ["/some/old/place"] and mk.symbols == ["KERNELS"]


def test_parse_errors(tmp_path):
    with pytest.raises(UtilityError):
        dl.parse_metakernel(tmp_path / "missing.tm")
    p = tmp_path / "bad.tm"
    p.write_text("no data here")
    with pytest.raises(UtilityError):
        dl.parse_metakernel(p)


def test_rewrite_keeps_everything_else_and_handles_long_paths(tmp_path):
    p = tmp_path / "x.tm"
    p.write_text(MK_TEXT)
    mk = dl.parse_metakernel(p)
    long = "F:/" + "/".join(["a_rather_long_folder_name"] * 5) + "/kernels"  # > 80 chars
    out = dl.rewrite_metakernel(mk, long)
    assert "KERNELS_TO_LOAD" in out and out.startswith("KPL/MK\nheader text") and out.rstrip().endswith("trailer")
    p2 = tmp_path / "y.tm"
    p2.write_text(out)
    mk2 = dl.parse_metakernel(p2)
    assert mk2.values == [long]  # '+' continuation re-assembled
    assert [e.rel for e in mk2.entries] == [e.rel for e in mk.entries]
    assert max(len(line) for line in out.splitlines()) <= 132


def test_split_host():
    assert dl.split_host("spiftp.esac.esa.int") == ("spiftp.esac.esa.int", 21)
    assert dl.split_host(" ftp://example.org/x ") == ("example.org", 21)
    assert dl.split_host("127.0.0.1:2121") == ("127.0.0.1", 2121)
    with pytest.raises(UtilityError):
        dl.split_host("  ")


def test_make_plan_validation(tmp_path):
    p = tmp_path / "x.tm"
    p.write_text(MK_TEXT)
    with pytest.raises(UtilityError):
        dl.make_plan(p, "")
    plan = dl.make_plan(p, tmp_path / "out", "/data/x/kernels/")
    assert plan.remote_root == "data/x/kernels"
    assert plan.new_metakernel == tmp_path / "out" / "data/x/kernels/mk/x.tm"


@pytest.fixture()
def ftp_server(tmp_path):
    pyftpdlib = pytest.importorskip("pyftpdlib")  # noqa: F841
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    # server tree = mock kernels published under data/SPICE/BEPICOLOMBO/kernels
    src_mk = mock.build(tmp_path / "src")
    served = tmp_path / "served"
    shutil.copytree(src_mk.parent.parent, served / "data/SPICE/BEPICOLOMBO/kernels")
    (served / "data/SPICE/BEPICOLOMBO/kernels/spk/big.bin").write_bytes(b"x" * 300_000)  # several 64 kB blocks
    auth = DummyAuthorizer()
    auth.add_anonymous(str(served))
    handler = type("H", (FTPHandler,), {"authorizer": auth})
    srv = FTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2, "handle_exit": False}, daemon=True)
    t.start()
    yield f"127.0.0.1:{srv.address[1]}", src_mk, served
    srv.close_all()


def _mk_with_extra(src_mk: Path, tmp_path: Path) -> Path:
    text = src_mk.read_text().replace("'$KERNELS/spk/mock.bsp'", "'$KERNELS/spk/mock.bsp', '$KERNELS/spk/big.bin'")
    p = tmp_path / "plan.tm"
    p.write_text(text)
    return p


def test_check_connection(ftp_server):
    host, _, _ = ftp_server
    assert dl.check_connection(host)
    with pytest.raises(UtilityError):
        dl.check_connection("127.0.0.1:1")  # nothing listens there


def test_full_download_and_resulting_metakernel_loads(ftp_server, tmp_path):
    host, src_mk, served = ftp_server
    mk = _mk_with_extra(src_mk, tmp_path)
    out = tmp_path / ("deep_" + "x" * 40) / ("deeper_" + "y" * 40)  # long path -> exercises '+' continuation
    plan = dl.make_plan(mk, out)
    events = []
    rep = dl.download(plan, host, progress=events.append)
    assert rep.ok and rep.downloaded == 6 and rep.existing == 0 and not rep.failed
    assert rep.bytes >= 300_000
    assert any(e.status == "bytes" for e in events) and events[-1].index == events[-1].total == 6
    for e in plan.metakernel.entries:
        assert plan.local(e).is_file()
        assert plan.local(e).read_bytes() == (served / plan.remote(e)).read_bytes()
    assert not list(plan.kernels_dir.rglob("*.part"))
    assert rep.metakernel == plan.new_metakernel and rep.metakernel.is_file()

    # the rewritten metakernel is directly usable by SPICE (relative-free, long path)
    ks = KernelSession()
    try:
        info = ks.load(rep.metakernel)
        assert info.total == 6
    finally:
        ks.unload()

    # second run: everything is already there
    rep2 = dl.download(plan, host)
    assert rep2.downloaded == 0 and rep2.existing == 6 and rep2.ok


def test_truncated_file_is_redownloaded_and_overwrite(ftp_server, tmp_path):
    host, src_mk, served = ftp_server
    mk = _mk_with_extra(src_mk, tmp_path)
    plan = dl.make_plan(mk, tmp_path / "out")
    dl.download(plan, host)
    big = plan.kernels_dir / "spk/big.bin"
    big.write_bytes(b"x" * 10)  # truncated copy
    rep = dl.download(plan, host)
    assert rep.downloaded == 1 and rep.existing == 5 and big.stat().st_size == 300_000
    rep = dl.download(plan, host, overwrite=True)
    assert rep.downloaded == 6


def test_missing_remote_file_is_reported_but_others_continue(ftp_server, tmp_path):
    host, src_mk, _ = ftp_server
    text = src_mk.read_text().replace("'$KERNELS/spk/mock.bsp'", "'$KERNELS/spk/nope.bsp', '$KERNELS/spk/mock.bsp'")
    p = tmp_path / "m.tm"
    p.write_text(text)
    plan = dl.make_plan(p, tmp_path / "out")
    rep = dl.download(plan, host)
    assert not rep.ok and [f[0] for f in rep.failed] == ["spk/nope.bsp"] and rep.downloaded == 5
    assert rep.metakernel is not None  # still written; the failure is reported


def test_cancel_stops_and_leaves_no_partial_files(ftp_server, tmp_path):
    host, src_mk, _ = ftp_server
    plan = dl.make_plan(_mk_with_extra(src_mk, tmp_path), tmp_path / "out")
    count = {"n": 0}

    def cancel():
        count["n"] += 1
        return count["n"] > 12  # inside the transfers

    rep = dl.download(plan, host, cancel=cancel)
    assert rep.cancelled and rep.metakernel is None
    assert not list(plan.kernels_dir.rglob("*.part"))


def test_unreachable_host_raises(tmp_path):
    src = mock.build(tmp_path / "s")
    plan = dl.make_plan(src, tmp_path / "out")
    with pytest.raises(UtilityError):
        dl.download(plan, "127.0.0.1:1")
