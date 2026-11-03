"""List and fetch the metakernels (``*.tm``) published in a server folder.

Default: https://spiftp.esac.esa.int/data/SPICE/BEPICOLOMBO/kernels/mk/

The folder is read as a web directory index (Apache / nginx / Python style HTML).  If that fails and the host is a
known FTP server, the same path is tried over FTP, so a firewall that only lets one of the two protocols through
still works.  Pure python (urllib / ftplib) - no Qt.
"""
from __future__ import annotations

import ftplib
import html
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urljoin, urlparse

from .errors import UtilityError

DEFAULT_URL = "https://spiftp.esac.esa.int/data/SPICE/BEPICOLOMBO/kernels/mk/"
_UA = "SimbioKernelUtility"


@dataclass
class RemoteMk:
    name: str
    url: str  # absolute http(s):// or ftp:// URL of the file
    size: int | None = None  # bytes
    modified: str = ""  # 'YYYY-MM-DD HH:MM' when the server tells

    # -- classification (see the description panel of the card) ----------------------------------
    _VERSIONED = re.compile(r"^(?P<fam>.+?)_v(?P<rel>\d+)_(?P<date>\d{8})_(?P<n>\d+)\.tm$", re.I)

    @property
    def versioned(self) -> tuple[str, str, str, str] | None:
        m = self._VERSIONED.match(self.name)
        return (m["fam"], m["rel"], m["date"], m["n"]) if m else None

    @property
    def kind(self) -> str:
        v = self.versioned
        if v:
            fam, rel, date, n = v
            return f"v{rel} · {date[:4]}-{date[4:6]}-{date[6:]} #{n}"
        low = self.name.lower()
        if low == "bc_ops.tm":
            return "latest operational"
        if low == "bc_plan.tm":
            return "latest planning"
        return "other"


def sort_key(m: RemoteMk):
    """Latest/main files first (alphabetical), then versioned copies newest first."""
    v = m.versioned
    if v is None:
        return (0, m.name.lower(), "")
    fam, rel, date, n = v
    return (1, "", "".join(chr(255 - ord(c)) for c in f"{date}{int(n):06d}{int(rel):06d}{fam}"))


# --------------------------------------------------------------------------------------------- helpers
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # bundled CA list: the frozen macOS/Linux builds do not always find the system store
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def normalize_url(text: str) -> str:
    t = text.strip().strip('"')
    if not t:
        raise UtilityError("Enter the URL of the folder that holds the metakernels.")
    if "://" not in t:
        t = "https://" + t
    u = urlparse(t)
    if u.scheme.lower() not in ("http", "https", "ftp") or not u.netloc:
        raise UtilityError(f"Unsupported URL: {t}\nUse an http(s):// or ftp:// address.")
    return t if t.endswith("/") else t + "/"


_DATE_PATTERNS = (
    (re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})"), lambda m: f"{m[1]} {m[2]}"),
    (re.compile(r"(\d{2}-[A-Za-z]{3}-\d{4}) (\d{2}:\d{2})"), lambda m: datetime.strptime(m[1], "%d-%b-%Y").strftime("%Y-%m-%d") + f" {m[2]}"),
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), lambda m: m[1]),
)
_SIZE = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?)\s?([KMGkmg])?(?:[Bb])?\s*$")


def _tail_info(tail: str) -> tuple[str, int | None]:
    """Date and size from the text that follows a link in a directory index row."""
    text = re.sub(r"<[^>]+>", " ", tail)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    modified = ""
    for rx, fmt in _DATE_PATTERNS:
        m = rx.search(text)
        if m:
            try:
                modified = fmt(m)
            except ValueError:
                modified = ""
            text = (text[:m.start()] + " " + text[m.end():]).strip()
            break
    size = None
    m = _SIZE.search(text)
    if m:
        mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[(m[2] or "").upper()]
        size = int(float(m[1]) * mult)
    return modified, size


_ANCHOR = re.compile(r"<a\s+[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>(.*?)(?=<a\s|\Z)", re.I | re.S)


def parse_index(page: str, base_url: str) -> list[RemoteMk]:
    """``*.tm`` links of a directory-index HTML page, with date and size when the page shows them."""
    out: dict[str, RemoteMk] = {}
    for m in _ANCHOR.finditer(page):
        href = html.unescape(m.group(1)).strip()
        if href.startswith(("?", "#")) or href.endswith("/"):
            continue
        path = unquote(urlparse(href).path)
        name = path.rsplit("/", 1)[-1]
        if not name.lower().endswith(".tm"):
            continue
        # the 'tail' of the last link may include page footer text: keep it short
        tail = re.split(r"</pre>|</table>|<hr|<address|</body", m.group(3), maxsplit=1, flags=re.I)[0]
        modified, size = _tail_info(tail[:300])
        out[name] = RemoteMk(name, urljoin(base_url, href), size, modified)
    return sorted(out.values(), key=sort_key)


# --------------------------------------------------------------------------------------------- listing
def _http_list(url: str, timeout: float) -> list[RemoteMk]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        final = r.geturl()
        page = r.read(8_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    return parse_index(page, final if final.endswith("/") else final + "/")


def _ftp_connect(host: str, port: int, timeout: float) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.encoding = "utf-8"
    ftp.connect(host, port, timeout=timeout)
    ftp.login()
    ftp.voidcmd("TYPE I")
    return ftp


def _ftp_list(url: str, timeout: float) -> list[RemoteMk]:
    u = urlparse(url)
    path = unquote(u.path).rstrip("/") or "/"
    ftp = _ftp_connect(u.hostname or "", u.port or 21, timeout)
    items: list[RemoteMk] = []
    try:
        try:
            for name, facts in ftp.mlsd(path, facts=["type", "size", "modify"]):
                if facts.get("type", "file") != "file" or not name.lower().endswith(".tm"):
                    continue
                mod = facts.get("modify", "")
                mod = f"{mod[:4]}-{mod[4:6]}-{mod[6:8]} {mod[8:10]}:{mod[10:12]}" if len(mod) >= 12 else ""
                items.append(RemoteMk(name, f"ftp://{u.netloc}{quote(path)}/{quote(name)}",
                                      int(facts["size"]) if facts.get("size", "").isdigit() else None, mod))
        except ftplib.error_perm:  # server without MLSD
            for full in ftp.nlst(path):
                name = full.rsplit("/", 1)[-1]
                if name.lower().endswith(".tm"):
                    try:
                        size = ftp.size(f"{path}/{name}")
                    except ftplib.Error:
                        size = None
                    items.append(RemoteMk(name, f"ftp://{u.netloc}{quote(path)}/{quote(name)}", size))
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    return sorted(items, key=sort_key)


def list_metakernels(url_text: str, timeout: float = 20.0) -> tuple[list[RemoteMk], str]:
    """Return (metakernels, method) where method is 'https', 'http' or 'ftp'."""
    url = normalize_url(url_text)
    scheme = urlparse(url).scheme.lower()
    errors: list[str] = []
    if scheme in ("http", "https"):
        try:
            items = _http_list(url, timeout)
            if items:
                return items, scheme
            errors.append(f"{scheme}: no *.tm links found in the page")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{scheme}: {getattr(exc, 'reason', exc)}")
        # fall back to FTP on the same host/path (the ESA server offers both)
        u = urlparse(url)
        try:
            items = _ftp_list(f"ftp://{u.hostname}{u.path}", timeout)
            if items:
                return items, "ftp"
            errors.append("ftp: no *.tm files found")
        except (ftplib.Error, OSError, EOFError) as exc:
            errors.append(f"ftp: {exc}")
    else:
        try:
            items = _ftp_list(url, timeout)
            if items:
                return items, "ftp"
            errors.append("ftp: no *.tm files found")
        except (ftplib.Error, OSError, EOFError) as exc:
            errors.append(f"ftp: {exc}")
    raise UtilityError("No metakernels found at\n" + url + "\n" + "\n".join(errors))


# --------------------------------------------------------------------------------------------- download
def fetch(mk: RemoteMk, dest_dir: str | Path, *, cancel: Callable[[], bool] = lambda: False,
          progress: Callable[[int, int], None] = lambda done, total: None, timeout: float = 30.0) -> Path:
    """Download one metakernel into ``dest_dir`` (overwriting: 'latest' files change over time). Returns the local path."""
    dest_dir = Path(str(dest_dir).strip().strip('"')).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / mk.name
    part = dest.with_name(dest.name + ".part")
    u = urlparse(mk.url)
    try:
        if u.scheme in ("http", "https"):
            req = urllib.request.Request(mk.url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r, open(part, "wb") as fh:
                total = int(r.headers.get("Content-Length") or mk.size or 0)
                done = 0
                while True:
                    if cancel():
                        raise UtilityError("Cancelled.")
                    block = r.read(64 * 1024)
                    if not block:
                        break
                    fh.write(block)
                    done += len(block)
                    progress(done, total)
        else:
            ftp = _ftp_connect(u.hostname or "", u.port or 21, timeout)
            try:
                done = 0
                total = mk.size or 0
                with open(part, "wb") as fh:
                    def on_block(b: bytes) -> None:
                        nonlocal done
                        if cancel():
                            raise UtilityError("Cancelled.")
                        fh.write(b)
                        done += len(b)
                        progress(done, total)

                    ftp.retrbinary(f"RETR {unquote(u.path)}", on_block, blocksize=64 * 1024)
            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass
        os.replace(part, dest)
        return dest
    except UtilityError:
        raise
    except (urllib.error.URLError, OSError, ftplib.Error, EOFError) as exc:
        raise UtilityError(f"Could not download {mk.name}\n{getattr(exc, 'reason', exc)}") from exc
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
