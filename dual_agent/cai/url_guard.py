"""HTTP(S) 請求前的公網／反 SSRF 檢查（供 fetch_url 等使用）。"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse


def validate_public_http_url(url: str) -> tuple[bool, str]:
    """
    僅允許 http/https，且解析後之 IP 不得為內網／本機／鏈路本機等。
    回傳 (ok, error_message)；ok 時 error_message 為空字串。
    """
    raw = (url or "").strip()
    if not raw:
        return False, "empty_url"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return False, "only_http_https"
    host = parsed.hostname
    if not host:
        return False, "missing_hostname"
    hl = host.lower()
    if hl == "localhost" or hl.endswith(".localhost"):
        return False, "blocked_host_localhost"
    # 阻擋常見「當成 hostname 的內網字樣」
    if re.match(r"^(10|127)\.\d+\.\d+\.\d+$", hl):
        return False, "blocked_literal_ip"
    if hl.startswith("192.168.") or hl.startswith("172."):
        # 172.16.0.0/12
        m = re.match(r"^172\.(\d+)\.", hl)
        if m and 16 <= int(m.group(1)) <= 31:
            return False, "blocked_literal_ip"

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as e:
        return False, f"dns_error:{e}"

    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"blocked_ip:{ip}"

    return True, ""
