"""HTTP helpers: plain requests for bulk data, and polite, public-only fetches for crawling."""

import gzip
import ipaddress
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from threading import Lock

from . import config


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def _decode(raw, enc):
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def request(url, data=None, headers=None, timeout=60, retries=3):
    hdrs = {"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    if isinstance(data, str):
        data = data.encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _decode(r.read(), r.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1) * (3 if e.code == 429 else 1))
                continue
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError):
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def is_public_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


_robots, _robots_lock = {}, Lock()


def allowed(url):
    parts = urllib.parse.urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            body = request(base + "/robots.txt", timeout=15, retries=1).decode("utf-8", "replace")
            rp.parse(body.splitlines())
        except Exception:
            rp.parse([])
        with _robots_lock:
            _robots[base] = rp
    return rp.can_fetch(config.USER_AGENT, url)


def fetch_page(url, timeout=25):
    """(final_url, html) for a public web page, or raises. Honours robots.txt."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not is_public_host(parts.hostname or ""):
        raise ValueError("not a public web address")
    if not allowed(url):
        raise PermissionError("robots.txt disallows this page")
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "text/html,*/*;q=0.5",
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"):
            raise ValueError("not an HTML page")
        raw = _decode(r.read(2_000_000), r.headers.get("Content-Encoding"))
        return r.geturl(), raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
