# -*- coding: utf-8 -*-
"""URL safety helpers.

The scrapers accept user-provided URLs.  A URL like ``http://127.0.0.1:11434``
or ``http://169.254.169.254`` must not be fetched by a workflow unless the
operator explicitly opts in with ``FW_ALLOW_PRIVATE_NETWORK=1``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL points at a non-public network target."""


def _is_public(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return False
    return bool(ip.is_global)


def assert_public_http_url(url: str, *, allow_private: bool | None = None) -> str:
    """Validate an HTTP(S) URL and reject loopback/private/link-local targets.

    Returns the original URL.  DNS failures are surfaced as UnsafeURLError so a
    bad host cannot be silently treated as safe.
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise UnsafeURLError("只支持 http/https 网址")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("网址缺少主机名")
    if allow_private is None:
        allow_private = os.environ.get("FW_ALLOW_PRIVATE_NETWORK") == "1"
    if allow_private:
        return url

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURLError("域名解析失败：%s" % exc) from exc

    addresses = {info[4][0] for info in infos if info and info[4]}
    if not addresses:
        raise UnsafeURLError("域名没有解析到地址：%s" % host)
    bad = [ip for ip in addresses if not _is_public(ip)]
    if bad:
        raise UnsafeURLError(
            "拒绝访问内网/本机地址：%s。如确实需要，设置 FW_ALLOW_PRIVATE_NETWORK=1。" % host
        )
    return url
