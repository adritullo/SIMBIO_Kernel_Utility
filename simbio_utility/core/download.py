"""Download the kernels listed in a (BepiColombo) metakernel from an ESA SPICE FTP server.

Pure python (ftplib / urllib) - no Qt, no SPICE - so it can run in a worker thread and be unit-tested against local servers.
Transport: anonymous FTP (port 21, default) or, with ``https=True``, the same paths over HTTPS (port 443) for networks that
block FTP.

Layout (same as the original ``KernelDownload_custom.py``)::

    <out_dir>/<remote_root>/<kernel as listed in the metakernel>          e.g. F:/BEPICOLOMBO_ops/data/SPICE/BEPICOLOMBO/kernels/spk/x.bsp
    <out_dir>/<remote_root>/mk/<metakernel name>                          copy of the metakernel with PATH_VALUES -> local kernels folder

``<remote_root>`` is also the path on the server (default ``data/SPICE/BEPICOLOMBO/kernels``).
"""
from __future__ import annotations

import ftplib
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from urllib.parse import quote

from .errors import UtilityError

DEFAULT_HOST = "spiftp.esac.esa.int"
DEFAULT_REMOTE_ROOT = "data/SPICE/BEPICOLOMBO/kernels"
_MAX_STRING = 78  # SPICE text-kernel strings are limited to 80 characters; longer values need the '+' continuation


# --------------------------------------------------------------------------------------------- metakernel parsing
@dataclass
class _Assignment:
    key: str
    op: str  # '=' or '+='
    items: list[str]
    value_span: tuple[int, int]  # [start, end) of the value text in the source (from after the operator to after ')')


def _data_blocks(text: str) -> list[tuple[int, int]]:
    """[start, end) offsets of the \\begindata ... \\begintext sections (to end of file if not closed)."""
    blocks, pos = [], 0
    for m in re.finditer(r"\\begindata", text):
        if m.start() < pos:
            continue
        e = re.search(r"\\begintext", text[m.end():])
        end = m.end() + e.start() if e else len(text)
        blocks.append((m.end(), end))
        pos = end
    return blocks


def _scan_assignments(text: str, start: int, end: int) -> list[_Assignment]:
    out: list[_Assignment] = []
    i = start
    key_re = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(\+?=)\s*")
    while i < end:
        m = key_re.search(text, i, end)
        if not m:
            break
        key, op = m.group(1).upper(), m.group(2)
        j = m.end()
        items: list[str] = []
        if j < end and text[j] == "(":
            j += 1
            while j < end:
                c = text[j]
                if c == ")":
                    j += 1
                    break
                if c in ", \t\r\n":
                    j += 1
                elif c == "'":
                    k, buf = j + 1, []
                    while k < end:
                        if text[k] == "'":
                            if k + 1 < end and text[k + 1] == "'":
                                buf.append("'")
                                k += 2
                                continue
                            break
                        buf.append(text[k])
                        k += 1
                    items.append("".join(buf))
                    j = k + 1
                else:
                    k = j
                    while k < end and text[k] not in ", \t\r\n)":
                        k += 1
                    items.append(text[j:k])
                    j = k
        elif j < end and text[j] == "'":
            k, buf = j + 1, []
            while k < end and text[k] != "'":
                buf.append(text[k])
                k += 1
            items.append("".join(buf))
            j = k + 1
        else:
            k = j
            while k < end and text[k] not in "\r\n":
                k += 1
            items.append(text[j:k].strip())
            j = k
        out.append(_Assignment(key, op, _join_continuations(items), (m.end(), j)))
        i = max(j, m.end())
    return out


def _join_continuations(items: list[str]) -> list[str]:
    """SPICE: a string ending in '+' continues in the next one."""
    out: list[str] = []
    carry = ""
    for it in items:
        s = carry + it
        if s.endswith("+"):
            carry = s[:-1]
            continue
        carry = ""
        out.append(s)
    if carry:
        out.append(carry)
    return out


@dataclass
class KernelEntry:
    listed: str  # as written in KERNELS_TO_LOAD
    rel: str  # path below the kernels root, '/'-separated (e.g. "spk/bc_mpo.bsp")

    @property
    def folder(self) -> str:
        return self.rel.split("/")[0] if "/" in self.rel else ""

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass
class Metakernel:
    path: Path
    text: str
    symbols: list[str]
    values: list[str]
    entries: list[KernelEntry]
    skipped: list[str] = field(default_factory=list)  # entries that cannot be mapped to a server path
    path_values_span: tuple[int, int] | None = None

    def local_path(self, listed: str) -> Path:
        """Where SPICE will look for a KERNELS_TO_LOAD item: ``$SYMBOL`` -> its PATH_VALUES entry (relative values are
        resolved against the metakernel folder, as KernelSession does), plain items are used as written."""
        item = listed.strip()
        m = re.match(r"\$([A-Za-z0-9_]+)[/\\]+(.+)$", item)
        base = self.path.parent
        if m:
            names = [x.upper() for x in self.symbols]
            i = names.index(m.group(1).upper()) if m.group(1).upper() in names else 0
            val = Path(self.values[i]).expanduser() if i < len(self.values) else Path(".")
            base = val if val.is_absolute() else self.path.parent / val
            item = m.group(2)
        p = Path(item).expanduser()
        return p if p.is_absolute() else base / item

    def missing(self) -> list[str]:
        """Items of KERNELS_TO_LOAD that are not on disk."""
        return [k for k in [e.listed for e in self.entries] + self.skipped if not self.local_path(k).is_file()]

    @property
    def total(self) -> int:
        return len(self.entries) + len(self.skipped)

    def counts_by_folder(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.folder or "."] = out.get(e.folder or ".", 0) + 1
        return dict(sorted(out.items()))


def parse_metakernel(path: str | Path) -> Metakernel:
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.is_file():
        raise UtilityError(f"Metakernel not found:\n{p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    asg: list[_Assignment] = []
    for s, e in _data_blocks(text):
        asg += _scan_assignments(text, s, e)
    if not asg:
        raise UtilityError(f"'{p.name}' has no \\begindata section: not a SPICE metakernel.")
    symbols: list[str] = []
    values: list[str] = []
    kernels: list[str] = []
    pv_span = None
    for a in asg:
        if a.key == "PATH_SYMBOLS":
            symbols = a.items if a.op == "=" else symbols + a.items
        elif a.key == "PATH_VALUES":
            values = a.items if a.op == "=" else values + a.items
            pv_span = a.value_span if pv_span is None else pv_span
        elif a.key == "KERNELS_TO_LOAD":
            kernels = a.items if a.op == "=" else kernels + a.items
    if not kernels:
        raise UtilityError(f"No KERNELS_TO_LOAD found in '{p.name}'.")
    entries, skipped = [], []
    for k in kernels:
        m = re.match(r"\$([A-Za-z0-9_]+)[/\\]+(.+)$", k.strip())
        if m and (not symbols or m.group(1).upper() in {s.upper() for s in symbols}):
            rel = m.group(2).replace("\\", "/").lstrip("/")
            entries.append(KernelEntry(k, rel))
        else:
            skipped.append(k)
    return Metakernel(p, text, symbols, values, entries, skipped, pv_span)


def _spice_string_list(value: str) -> str:
    """Quote ``value`` for a text kernel, using '+' continuation when it exceeds the 80-character limit."""
    value = value.replace("'", "''")
    if len(value) <= _MAX_STRING:
        return f"'{value}'"
    parts = [value[i:i + _MAX_STRING - 1] for i in range(0, len(value), _MAX_STRING - 1)]
    return ("\n" + " " * 24).join(f"'{p}+'" if n < len(parts) - 1 else f"'{p}'" for n, p in enumerate(parts))


def rewrite_metakernel(mk: Metakernel, kernels_dir: str) -> str:
    """Copy of the metakernel text with PATH_VALUES pointing at ``kernels_dir`` (one value per PATH_SYMBOL)."""
    if mk.path_values_span is None:
        raise UtilityError("The metakernel has no PATH_VALUES to rewrite.")
    n = max(1, len(mk.symbols) or len(mk.values))
    new = "( " + (",\n" + " " * 24).join([_spice_string_list(kernels_dir)] * n) + " )"
    s, e = mk.path_values_span
    return mk.text[:s] + new + mk.text[e:]


# --------------------------------------------------------------------------------------------- planning
@dataclass
class DownloadPlan:
    metakernel: Metakernel
    out_dir: Path
    remote_root: str
    host: str = DEFAULT_HOST

    @property
    def kernels_dir(self) -> Path:
        return self.out_dir / self.remote_root

    def local(self, e: KernelEntry) -> Path:
        return self.kernels_dir / e.rel

    def remote(self, e: KernelEntry) -> str:
        return f"{self.remote_root}/{e.rel}"

    @property
    def new_metakernel(self) -> Path:
        return self.kernels_dir / "mk" / self.metakernel.path.name

    def present(self) -> int:
        return sum(1 for e in self.metakernel.entries if self.local(e).is_file())


def make_plan(metakernel: str | Path, out_dir: str | Path, remote_root: str = DEFAULT_REMOTE_ROOT) -> DownloadPlan:
    out = Path(str(out_dir).strip().strip('"')).expanduser()
    if not str(out_dir).strip():
        raise UtilityError("Choose an output folder.")
    root = remote_root.strip().strip("/").replace("\\", "/")
    if not root:
        raise UtilityError("The remote kernels path is empty.")
    return DownloadPlan(parse_metakernel(metakernel), out, root)


def infer_out_dir(metakernel: str | Path, remote_root: str = DEFAULT_REMOTE_ROOT) -> Path | None:
    """If the metakernel sits in ``<out>/<remote_root>/mk/`` (the layout this app and ESA use), return ``<out>``."""
    parts = Path(str(metakernel)).expanduser().parent.parts
    root = remote_root.strip("/").split("/")
    n = len(root)
    if len(parts) > n + 1 and parts[-1].lower() == "mk" and [x.lower() for x in parts[-n - 1:-1]] == [x.lower() for x in root]:
        return Path(*parts[:-n - 1])
    return None


def split_host(text: str, default_port: int = 21) -> tuple[str, int]:
    """'spiftp.esac.esa.int', 'ftp://host', 'host:2121' -> (host, port)."""
    t = text.strip()
    t = re.sub(r"^[a-zA-Z]+://", "", t).split("/")[0]
    if not t:
        raise UtilityError("Enter a server host name.")
    if ":" in t:
        h, _, pt = t.rpartition(":")
        if pt.isdigit():
            return h, int(pt)
    return t, default_port


def parse_server(text: str, https: bool = False) -> tuple[str, str, int]:
    """(scheme, host, port) of the server field.  ``scheme`` is 'ftp' (port 21), or 'https' (port 443) when ``https`` is set.

    An explicit prefix wins: 'https://host' / 'http://host' always use the web protocol, 'ftp://host' always FTP."""
    m = re.match(r"^\s*([a-zA-Z]+)://", text)
    scheme = m.group(1).lower() if m else ("https" if https else "ftp")
    if scheme not in ("ftp", "http", "https"):
        raise UtilityError(f"Unsupported protocol '{scheme}://' (use ftp, http or https).")
    host, port = split_host(text, {"ftp": 21, "http": 80, "https": 443}[scheme])
    return scheme, host, port


# --------------------------------------------------------------------------------------------- download
@dataclass
class Progress:
    index: int  # 1-based file number
    total: int
    name: str
    status: str  # 'start' | 'bytes' | 'done' | 'exists' | 'failed'
    done: int = 0
    size: int = 0
    message: str = ""


@dataclass
class Report:
    downloaded: int = 0
    existing: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False
    metakernel: Path | None = None
    skipped: list[str] = field(default_factory=list)
    bytes: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed and not self.cancelled

    def summary(self) -> str:
        s = f"{self.downloaded} downloaded ({self.bytes / 1e6:.1f} MB), {self.existing} already present"
        if self.failed:
            s += f", {len(self.failed)} FAILED"
        if self.cancelled:
            s += " - cancelled"
        return s + f" in {self.seconds:.0f} s"


class _Cancelled(Exception):
    pass


def _connect(host: str, port: int, timeout: float) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.encoding = "utf-8"
    ftp.connect(host, port, timeout=timeout)
    ftp.login()  # anonymous
    ftp.voidcmd("TYPE I")
    return ftp


class _NotAvailable(Exception):
    """The server says the file does not exist / may not be read (retrying will not help)."""


class _FtpTransport:
    """Anonymous FTP (port 21)."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.ftp: ftplib.FTP | None = None
        self.reconnect()

    def reconnect(self) -> None:
        self.close()
        try:
            self.ftp = _connect(self.host, self.port, self.timeout)
        except Exception as exc:
            raise UtilityError(f"Cannot connect to {self.host}:{self.port}\n{exc}\n"
                               "If port 21 is blocked on your network, tick 'Use HTTPS (port 443)'.") from exc

    def greeting(self) -> str:
        w = self.ftp.getwelcome()
        return w.splitlines()[0] if w else "connected"

    def size(self, path: str) -> int | None:
        try:
            return self.ftp.size(path)
        except ftplib.error_perm:
            return None

    def retrieve(self, path: str, on_block: Callable[[bytes], None]) -> None:
        try:
            self.ftp.retrbinary(f"RETR {path}", on_block, blocksize=64 * 1024)
        except ftplib.error_perm as exc:
            raise _NotAvailable(str(exc).strip()) from exc

    #: errors that mean 'network trouble: reconnect and retry'
    transient = (OSError, EOFError, ftplib.Error)

    def close(self) -> None:
        f, self.ftp = getattr(self, "ftp", None), None
        if f is not None:
            try:
                f.quit()
            except Exception:
                try:
                    f.close()
                except Exception:
                    pass


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # frozen macOS/Linux builds do not always find the system CA store
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class _HttpTransport:
    """The same folders served over http(s) (port 443 for https): works where FTP is blocked."""

    def __init__(self, scheme: str, host: str, port: int, timeout: float) -> None:
        self.scheme, self.host, self.port, self.timeout = scheme, host, port, timeout
        default = {"http": 80, "https": 443}[scheme]
        self.base = f"{scheme}://{host}" + ("" if port == default else f":{port}")
        self.ctx = _ssl_context() if scheme == "https" else None
        self.reconnect()

    def _url(self, path: str) -> str:
        return f"{self.base}/{quote(path.lstrip('/'))}"

    def _open(self, path: str, method: str = "GET"):
        req = urllib.request.Request(self._url(path), method=method, headers={"User-Agent": "SimbioKernelUtility"})
        return urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx)

    def reconnect(self) -> None:  # stateless: nothing to re-open, but fail early if the server is unreachable
        pass

    def greeting(self) -> str:
        try:
            with self._open("", "HEAD") as r:
                return f"{self.base} - HTTP {r.status}"
        except urllib.error.HTTPError as exc:  # a reply (even 403/404 on the root) proves the server is reachable
            return f"{self.base} - HTTP {exc.code}"
        except Exception as exc:
            raise UtilityError(f"Cannot connect to {self.base}\n{getattr(exc, 'reason', exc)}") from exc

    def size(self, path: str) -> int | None:
        try:
            with self._open(path, "HEAD") as r:
                n = r.headers.get("Content-Length")
                return int(n) if n and n.isdigit() else None
        except urllib.error.HTTPError:
            return None

    def retrieve(self, path: str, on_block: Callable[[bytes], None]) -> None:
        try:
            with self._open(path) as r:
                while True:
                    block = r.read(64 * 1024)
                    if not block:
                        break
                    on_block(block)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404, 410):
                raise _NotAvailable(f"HTTP {exc.code} {exc.reason}") from exc
            raise

    transient = (OSError, EOFError, urllib.error.URLError)

    def close(self) -> None:
        pass


def _transport(server_text: str, https: bool, timeout: float):
    scheme, host, port = parse_server(server_text, https)
    if scheme == "ftp":
        return _FtpTransport(host, port, timeout)
    return _HttpTransport(scheme, host, port, timeout)


def check_connection(host_text: str, timeout: float = 10.0, https: bool = False) -> str:
    tr = _transport(host_text, https, timeout)
    try:
        return tr.greeting()
    finally:
        tr.close()


def download(plan: DownloadPlan, host_text: str | None = None, *, overwrite: bool = False,
             cancel: Callable[[], bool] = lambda: False, progress: Callable[[Progress], None] = lambda p: None,
             timeout: float = 30.0, retries: int = 2, https: bool = False) -> Report:
    """Download every kernel of the plan.  ``https=True`` fetches the same paths over HTTPS (port 443) instead of FTP
    (port 21) - for networks that block FTP."""
    server = host_text or plan.host
    rep = Report(skipped=list(plan.metakernel.skipped))
    t0 = time.time()
    entries = plan.metakernel.entries
    total = len(entries)
    tr = None  # transport: FTP or HTTP(S)
    last_emit = [0.0]

    def connect():
        return _transport(server, https, timeout)

    def remote_size(f, path: str) -> int | None:
        return f.size(path)

    try:
        tr = connect()
        tr.greeting()  # fail fast (UtilityError) when the server cannot be reached at all
        for n, e in enumerate(entries, 1):
            if cancel():
                rep.cancelled = True
                break
            dest = plan.local(e)
            remote = plan.remote(e)
            if dest.is_file() and not overwrite:
                # an interrupted earlier run leaves no final file (we write to .part), so presence == complete;
                # still compare sizes when the server can tell us, to catch truncated/foreign files
                try:
                    rs = remote_size(tr, remote)
                except tr.transient:
                    tr.close()
                    tr = connect()
                    rs = remote_size(tr, remote)
                if rs is None or rs == dest.stat().st_size:
                    rep.existing += 1
                    progress(Progress(n, total, e.rel, "exists", dest.stat().st_size, dest.stat().st_size))
                    continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            err = ""
            for attempt in range(retries + 1):
                try:
                    size = remote_size(tr, remote) or 0
                    progress(Progress(n, total, e.rel, "start", 0, size))
                    done = 0
                    with open(part, "wb") as fh:
                        def on_block(b: bytes) -> None:
                            nonlocal done
                            if cancel():
                                raise _Cancelled()
                            fh.write(b)
                            done += len(b)
                            now = time.time()
                            if now - last_emit[0] > 0.1:
                                last_emit[0] = now
                                progress(Progress(n, total, e.rel, "bytes", done, size))

                        tr.retrieve(remote, on_block)
                    os.replace(part, dest)
                    rep.downloaded += 1
                    rep.bytes += done
                    progress(Progress(n, total, e.rel, "done", done, done or size))
                    err = ""
                    break
                except _Cancelled:
                    rep.cancelled = True
                    err = ""
                    break
                except _NotAvailable as exc:  # 550 / HTTP 404: no such file / not allowed - retrying will not help
                    err = f"not available on the server ({exc})"
                    break
                except tr.transient as exc:  # network trouble: reconnect and retry
                    err = str(getattr(exc, "reason", exc)).strip() or exc.__class__.__name__
                    tr.close()
                    if attempt < retries:
                        time.sleep(1.0)
                        tr = connect()
            if part.exists() and (err or rep.cancelled):
                try:
                    part.unlink()
                except OSError:
                    pass
            if rep.cancelled:
                break
            if err:
                rep.failed.append((e.rel, err))
                progress(Progress(n, total, e.rel, "failed", 0, 0, err))
        if not rep.cancelled:
            plan.new_metakernel.parent.mkdir(parents=True, exist_ok=True)
            text = rewrite_metakernel(plan.metakernel, plan.kernels_dir.as_posix())
            plan.new_metakernel.write_text(text, encoding="utf-8", newline="\n")
            rep.metakernel = plan.new_metakernel
    finally:
        if tr is not None:
            tr.close()
        rep.seconds = time.time() - t0
    return rep
