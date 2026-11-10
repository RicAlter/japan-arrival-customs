# -*- coding: utf-8 -*-
"""带来源、抓取时间和有效期的查询缓存。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable


class CacheStore:
    def __init__(self, path: str | Path, clock: Callable[[], float] | None = None):
        self.path = Path(path)
        self.clock = clock or time.time
        self._data: dict[str, Any] = {"schema_version": 1, "entries": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), dict):
                self._data = data
        except Exception:
            self._data = {"schema_version": 1, "entries": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def key(site_id: str, jan: str) -> str:
        return f"{site_id}:{jan}"

    def get(self, site_id: str, jan: str) -> dict[str, Any] | None:
        key = self.key(site_id, jan)
        entry = self._data.get("entries", {}).get(key)
        if not entry:
            return None
        if float(entry.get("expires_at", 0)) <= self.clock():
            return None
        return entry

    def put(self, site_id: str, jan: str, url: str, data: dict[str, Any], ttl_seconds: int) -> dict[str, Any]:
        now = self.clock()
        key = self.key(site_id, jan)
        entry = {
            "site_id": site_id,
            "jan": jan,
            "url": url,
            "fetched_at": data.get("fetched_at") or data.get("queried_at") or "",
            "cached_at": now,
            "expires_at": now + max(60, int(ttl_seconds)),
            "ttl_seconds": int(ttl_seconds),
            "data": data,
        }
        self._data.setdefault("entries", {})[key] = entry
        self._save()
        return entry

    def delete(self, site_id: str, jan: str) -> bool:
        key = self.key(site_id, jan)
        if key in self._data.get("entries", {}):
            del self._data["entries"][key]
            self._save()
            return True
        return False

    def clear(self, expired_only: bool = False) -> int:
        entries = self._data.get("entries", {})
        if not expired_only:
            count = len(entries)
            entries.clear()
            self._save()
            return count
        now = self.clock()
        expired = [k for k, v in entries.items() if float(v.get("expires_at", 0)) <= now]
        for k in expired:
            del entries[k]
        if expired:
            self._save()
        return len(expired)

    def stats(self) -> dict[str, Any]:
        entries = self._data.get("entries", {})
        now = self.clock()
        return {
            "path": str(self.path),
            "entries": len(entries),
            "expired": sum(1 for v in entries.values() if float(v.get("expires_at", 0)) <= now),
            "sites": sorted({v.get("site_id", "") for v in entries.values() if v.get("site_id")}),
        }
