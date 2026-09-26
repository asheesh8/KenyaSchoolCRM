"""HTTP helpers: cached downloads for bulk data, polite fetches for crawling."""

import gzip
import hashlib
import ipaddress
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from threading import Lock

from . import config

_insecure = ssl.create_default_context()
_insecure.check_hostname = False
_insecure.verify_mode = ssl.CERT_NONE


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def _decode_body(raw, encoding):
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def request(url, data=None, headers=None, timeout=60, method=None, retries=3, backoff=5):
    """Plain request with retries on 429/5xx. Returns bytes."""
    hdrs = {"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    if isinstance(data, str):
        data = data.encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _decode_body(r.read(), r.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = backoff * (attempt + 1) * (3 if e.code == 429 else 1)
                log(f"  {e.code} from {urllib.parse.urlsplit(url).netloc}; retrying in {wait}s")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
    raise last


def request_json(url, **kw):
    return json.loads(request(url, **kw))


def cached_download(url, name=None, max_age_days=30, timeout=300):
    """Download once into data/cache; re-download when older than max_age_days."""
    config.ensure_dirs()
    name = name or hashlib.sha1(url.encode()).hexdigest()[:16] + "_" + url.rsplit("/", 1)[-1]
    path = config.CACHE / name
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        return path
    log(f"  downloading {url}")
    hdrs = {"User-Agent": config.USER_AGENT}
    req = urllib.request.Request(url, headers=hdrs)
    tmp = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, socket.timeout, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    tmp.replace(path)
    return path


# ---------------------------------------------------------------- crawling

_host_ok = {}
_host_ok_lock = Lock()


def is_public_url(url):
    """Only http(s) to hosts on the public internet: school websites are
    untrusted input, and a listed URL must never reach this computer's network."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return False
    host = parts.hostname.lower()
    with _host_ok_lock:
        if host in _host_ok:
            return _host_ok[host]
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)}
        ok = bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)
    except (socket.gaierror, UnicodeError, ValueError, OSError):
        ok = True  # unresolvable: the fetch itself will fail with "dns"
    with _host_ok_lock:
        _host_ok[host] = ok
    return ok


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 6

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_url(newurl):
            raise urllib.error.URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(ctx):
    return urllib.request.build_opener(_CheckedRedirects(), urllib.request.HTTPSHandler(context=ctx))


class Page:
    __slots__ = ("url", "final_url", "status", "html", "error", "content_type")

    def __init__(self, url, final_url=None, status=0, html="", error=None, content_type=""):
        self.url, self.final_url, self.status = url, final_url or url, status
        self.html, self.error, self.content_type = html, error, content_type

    @property
    def ok(self):
        return self.status == 200 and bool(self.html)


_robots = {}
_robots_lock = Lock()


def robots_allows(url):
    parts = urllib.parse.urlsplit(url)
    key = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        rp = _robots.get(key)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            body = fetch_raw(key + "/robots.txt", timeout=8, max_bytes=200_000)
            if body.status == 200 and "html" not in body.content_type:
                rp.parse(body.html.splitlines())
            else:
                rp.parse([])
        except Exception:
            rp.parse([])
        with _robots_lock:
            _robots[key] = rp
    return rp.can_fetch("KenyaSchoolsDirectory", url)


def fetch_raw(url, timeout=12, max_bytes=2_000_000):
    """GET a web page. Falls back to an unverified TLS context, because many
    small school sites run expired or mismatched certificates (pages are only read)."""
    hdrs = {
        "User-Agent": config.BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-KE,en;q=0.9,sw;q=0.6",
        "Accept-Encoding": "gzip, deflate",
    }
    if not is_public_url(url):
        return Page(url, url, 0, "", "not a public address")
    last_err = None
    for ctx in (ssl.create_default_context(), _insecure):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with _opener(ctx).open(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                raw = r.read(max_bytes)
                raw = _decode_body(raw, r.headers.get("Content-Encoding"))
                charset = r.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return Page(url, r.geturl(), r.status, text, None, ctype)
        except urllib.error.HTTPError as e:
            return Page(url, url, e.code, "", f"HTTP {e.code}")
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
                last_err = f"TLS: {reason}"
                continue
            return Page(url, url, 0, "", _describe(reason))
        except ssl.SSLError as e:
            last_err = f"TLS: {e}"
            continue
        except (socket.timeout, TimeoutError):
            return Page(url, url, 0, "", "timeout")
        except (ConnectionError, OSError, ValueError) as e:
            return Page(url, url, 0, "", _describe(e))
        except Exception as e:  # malformed responses from odd servers
            return Page(url, url, 0, "", f"{type(e).__name__}: {e}"[:200])
    return Page(url, url, 0, "", last_err or "TLS error")


def _describe(reason):
    s = str(reason)
    if isinstance(reason, socket.gaierror) or "Name or service not known" in s or "nodename nor servname" in s:
        return "dns"
    if "refused" in s.lower():
        return "refused"
    if "timed out" in s.lower():
        return "timeout"
    return s[:200]
