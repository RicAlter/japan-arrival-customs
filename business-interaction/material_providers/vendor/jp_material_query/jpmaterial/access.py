# -*- coding: utf-8 -*-
"""站点授权、403 熔断、429 退避状态。"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import AccessStatus, SitePolicy


@dataclass
class AccessDecision:
    allowed: bool
    status: AccessStatus
    reason: str = ""
    retry_after: float = 0.0


class AccessRegistry:
    """持久化每个站点的访问状态。

    403：停止该站自动访问，直到人工 reset。
    429：按 Retry-After 退避；连续超过上限后临时熔断。
    """

    def __init__(self, path: str | Path, clock: Callable[[], float] | None = None):
        self.path = Path(path)
        self.clock = clock or time.time
        self._data: dict[str, Any] = {"schema_version": 1, "sites": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sites"), dict):
                self._data = data
        except Exception:
            self._data = {"schema_version": 1, "sites": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def _site(self, site_id: str) -> dict[str, Any]:
        return self._data.setdefault("sites", {}).setdefault(site_id, {})

    def check(self, policy: SitePolicy) -> AccessDecision:
        if not policy.enabled:
            return AccessDecision(False, AccessStatus.SITE_DISABLED, "站点已关闭")
        if not policy.authorized:
            return AccessDecision(False, AccessStatus.NOT_AUTHORIZED, "尚未获得站方授权")
        state = self._site(policy.site_id)
        now = self.clock()
        if state.get("blocked"):
            until = state.get("blocked_until")
            if until is None or now < float(until):
                status = AccessStatus.BLOCKED_403 if state.get("last_http_status") == 403 else AccessStatus.RATE_LIMITED
                return AccessDecision(False, status, state.get("reason", "站点访问受限"))
            # 临时熔断到期，自动解除；403 永久熔断的 blocked_until 为 None
            state["blocked"] = False
            state["blocked_until"] = None
            self._save()
        return AccessDecision(True, AccessStatus.OK)

    def record_success(self, site_id: str) -> None:
        state = self._site(site_id)
        state["consecutive_429"] = 0
        state["last_http_status"] = 200
        state["updated_at"] = self.clock()
        self._save()

    def record_403(self, site_id: str, url: str = "") -> None:
        state = self._site(site_id)
        state.update({
            "blocked": True,
            "blocked_until": None,
            "last_http_status": 403,
            "reason": "HTTP 403：已停止该站自动访问，需人工核验授权后 reset",
            "last_url": url,
            "updated_at": self.clock(),
        })
        self._save()

    def record_429(self, site_id: str, retry_after: float, max_retries: int, url: str = "") -> None:
        state = self._site(site_id)
        count = int(state.get("consecutive_429", 0)) + 1
        state["consecutive_429"] = count
        state["last_http_status"] = 429
        state["last_url"] = url
        state["last_retry_after"] = retry_after
        state["updated_at"] = self.clock()
        if count > max_retries:
            state["blocked"] = True
            state["blocked_until"] = self.clock() + max(300.0, retry_after)
            state["reason"] = f"连续 429 超过 {max_retries} 次，临时熔断"
        self._save()

    def reset(self, site_id: str) -> bool:
        state = self._site(site_id)
        if not state:
            return False
        state.update({
            "blocked": False,
            "blocked_until": None,
            "consecutive_429": 0,
            "reason": "人工 reset",
            "updated_at": self.clock(),
        })
        self._save()
        return True

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._data, ensure_ascii=False))
