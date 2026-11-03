"""Search Kernel: directory-index parsing, listing and fetching against local HTTP and FTP servers."""
import functools
import http.server
import threading
from pathlib import Path

import pytest

from simbio_utility.core import mkindex as mi
from simbio_utility.core.errors import UtilityError

BASE = "https://spiftp.esac.esa.int/data/SPICE/BEPICOLOMBO/kernels/mk/"
APACHE = '''<pre><img src="/icons/blank.gif"> <a href="?C=N;O=D">Name</a> <a href="?C=M;O=A">Last modified</a> <a href="?C=S;O=A">Size</a><hr>
<img src="/icons/back.gif"> <a href="/data/">Parent Directory</a>   -
<img src="/icons/unknown.gif"> <a href="bc_ops.tm">bc_ops.tm</a>   2026-10-30 12:01  3.4K
<img src="/icons/unknown.gif"> <a href="bc_plan.tm">bc_plan.tm</a>   2026-11-02 08:15  4.1K
<img src="/icons/unknown.gif"> <a href="bc_ops_v433_20260902_001.tm">bc_ops_v433_20260902_001.tm</a> 2026-09-02 10:00  3.3K
<img src="/icons/unknown.gif"> <a href="bc_plan_v440_20261015_002.tm">bc_plan_v440_20261015_002.tm</a> 2026-10-15 10:00  4.0K
<img src="/icons/text.gif"> <a href="readme.txt">readme.txt</a>  2026-01-01 00:00  1.0K
<hr></pre><address>Apache/2.4.41 (Ubuntu) Server at spiftp.esac.esa.int Port 80</address>'''
NGINX = '<pre><a href="../">../</a>\n<a href="bc_ops.tm">bc_ops.tm</a>      03-Nov-2026 11:00   3500\n</pre>'


def test_parse_apache_pre():
    items = mi.parse_index(APACHE, BASE)
    assert [m.name for m in items] == ["bc_ops.tm", "bc_plan.tm", "bc_plan_v440_20261015_002.tm", "bc_ops_v433_20260902_001.tm"]
    ops = items[0]
    assert ops.url == BASE + "bc_ops.tm" and ops.modified == "2026-10-30 12:01" and ops.size == int(3.4 * 1024)
    assert ops.kind == "latest operational" and items[1].kind == "latest planning"
    assert items[2].versioned == ("bc_plan", "440", "20261015", "002")
    assert items[2].kind == "v440 · 2026-10-15 #002"
    assert all(m.name != "readme.txt" for m in items)  # only *.tm
    assert all(m.size != 80 for m in items)  # the 'Port 80' footer is not a size


def test_parse_nginx_and_plain():
    m = mi.parse_index(NGINX, BASE)[0]
    assert (m.name, m.size, m.modified) == ("bc_ops.tm", 3500, "2026-11-03 11:00")
    plain = mi.parse_index('<ul><li><a href="a.tm">a.tm</a></li><li><a href="sub/">sub/</a></li></ul>', BASE)
    assert [x.name for x in plain] == ["a.tm"] and plain[0].size is None


def test_normalize_url():
    assert mi.normalize_url("example.org/mk") == "https://example.org/mk/"
    assert mi.normalize_url(" ftp://h/p/ ") == "ftp://h/p/"
    for bad in ("", "  ", "file:///x"):
        with pytest.raises(UtilityError):
            mi.normalize_url(bad)


@pytest.fixture()
def http_dir(tmp_path):
    root = tmp_path / "www"
    mk = root / "data/SPICE/BEPICOLOMBO/kernels/mk"
    mk.mkdir(parents=True)
    (mk / "bc_ops.tm").write_bytes(b"ops\n")  # bytes: write_text would turn \n into \r\n on Windows and change the sizes
    (mk / "bc_plan.tm").write_bytes(b"plan\n" * 50_000)
    (mk / "bc_ops_v433_20260902_001.tm").write_bytes(b"old\n")
    (mk / "notes.txt").write_text("x")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/data/SPICE/BEPICOLOMBO/kernels/mk/"
    srv.shutdown()


def test_list_and_fetch_over_http(http_dir, tmp_path):
    items, method = mi.list_metakernels(http_dir)
    assert method == "http"
    assert [m.name for m in items] == ["bc_ops.tm", "bc_plan.tm", "bc_ops_v433_20260902_001.tm"]
    seen = []
    p = mi.fetch(items[1], tmp_path / "dl", progress=lambda d, t: seen.append((d, t)))
    assert p == tmp_path / "dl" / "bc_plan.tm" and p.stat().st_size == 250_000
    assert seen and seen[-1][0] == 250_000 and not list((tmp_path / "dl").glob("*.part"))
    p2 = mi.fetch(items[0], tmp_path / "dl")  # overwrite-safe
    assert p2.read_bytes() == b"ops\n"


def test_fetch_cancel_and_errors(http_dir, tmp_path):
    items, _ = mi.list_metakernels(http_dir)
    with pytest.raises(UtilityError):
        mi.fetch(items[1], tmp_path / "c", cancel=lambda: True)
    assert not list((tmp_path / "c").glob("*"))  # nothing left behind
    with pytest.raises(UtilityError):
        mi.fetch(mi.RemoteMk("nope.tm", http_dir + "nope.tm"), tmp_path / "c")


def test_list_errors():
    with pytest.raises(UtilityError) as e:
        mi.list_metakernels("http://127.0.0.1:1/x/", timeout=3)
    assert "No metakernels found" in str(e.value)


def test_list_and_fetch_over_ftp(tmp_path):
    pytest.importorskip("pyftpdlib")
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    served = tmp_path / "ftp"
    mk = served / "data/SPICE/BEPICOLOMBO/kernels/mk"
    mk.mkdir(parents=True)
    (mk / "bc_ops.tm").write_bytes(b"ops via ftp\n")
    (mk / "bc_plan_v1_20260101_001.tm").write_bytes(b"v\n")
    (mk / "other.txt").write_text("x")
    auth = DummyAuthorizer()
    auth.add_anonymous(str(served))
    srv = FTPServer(("127.0.0.1", 0), type("H", (FTPHandler,), {"authorizer": auth}))
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2, "handle_exit": False}, daemon=True).start()
    try:
        url = f"ftp://127.0.0.1:{srv.address[1]}/data/SPICE/BEPICOLOMBO/kernels/mk/"
        items, method = mi.list_metakernels(url)
        assert method == "ftp" and [m.name for m in items] == ["bc_ops.tm", "bc_plan_v1_20260101_001.tm"]
        assert items[0].size == len(b"ops via ftp\n") and len(items[0].modified) == 16
        p = mi.fetch(items[0], tmp_path / "out")
        assert p.read_bytes() == b"ops via ftp\n"
    finally:
        srv.close_all()
