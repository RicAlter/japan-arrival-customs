# -*- coding: utf-8 -*-
"""最小 HTTP 传输层。

默认禁用系统代理，避免使用代理轮换绕过站方限制；不实现任何反爬绕过。
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


@dataclass
class HttpResponse:
    url: str
    status_code: int | None = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    def header(self, name: str) -> str:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return ""


class UrllibTransport:
    def __init__(self, timeout: float = 20.0, user_agent: str | None = None):
        self.timeout = timeout
        self.user_agent = user_agent or (
            "JPMaterialQuery/0.1 (internal, offline-first; contact: data team)"
        )
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        start = time.time()
        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en;q=0.8",
        }
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                text = self._decode(raw, resp.headers.get("Content-Type", ""))
                return HttpResponse(
                    url=resp.geturl(),
                    status_code=int(resp.status),
                    text=text,
                    headers={k: v for k, v in resp.headers.items()},
                    elapsed_ms=int((time.time() - start) * 1000),
                )
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except Exception:
                raw = b""
            return HttpResponse(
                url=url,
                status_code=int(exc.code),
                text=self._decode(raw, exc.headers.get("Content-Type", "") if exc.headers else ""),
                headers={k: v for k, v in (exc.headers.items() if exc.headers else [])},
                error=f"HTTP {exc.code}",
                elapsed_ms=int((time.time() - start) * 1000),
            )
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            return HttpResponse(
                url=url,
                status_code=None,
                error=f"network: {exc}",
                elapsed_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:
            return HttpResponse(
                url=url,
                status_code=None,
                error=f"transport: {exc}",
                elapsed_ms=int((time.time() - start) * 1000),
            )

    @staticmethod
    def _decode(raw: bytes, content_type: str) -> str:
        charset = "utf-8"
        if "charset=" in content_type.lower():
            charset = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        for enc in (charset, "utf-8", "cp932", "shift_jis", "euc-jp", "gb18030"):
            try:
                return raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", errors="replace")
