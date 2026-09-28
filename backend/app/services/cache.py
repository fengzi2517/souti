"""缓存与限流：Redis 实现，连接失败自动降级为进程内存版（开发兜底）"""
import hashlib
import json
import time
from collections import defaultdict

import redis.asyncio as aioredis

from ..config import settings

_memory_store: dict[str, tuple[float, str]] = {}
_memory_rate: dict[str, list[int]] = defaultdict(list)
_memory_counter: dict[str, tuple[int, float]] = {}  # (计数, 过期时间)


def _norm_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class CacheService:
    """Redis 缓存/限流；断连自动降级内存版，冷却期过后重试恢复连接。"""

    DEGRADED_RETRY_SECONDS = 60  # 降级后每隔 60s 允许重试一次 Redis 连接

    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._degraded_at: float | None = None
        self._last_purge = 0.0

    async def _get_redis(self) -> aioredis.Redis | None:
        if self._degraded_at is not None:
            if time.time() - self._degraded_at < self.DEGRADED_RETRY_SECONDS:
                return None
            self._degraded_at = None  # 冷却期已过，尝试重连（Redis 可能已恢复）
        if self._redis is None:
            try:
                r = aioredis.from_url(settings.redis_url, decode_responses=True)
                await r.ping()
                self._redis = r
            except Exception:  # noqa: BLE001
                self._degraded_at = time.time()
                return None
        return self._redis

    def _purge_memory(self) -> None:
        """清扫内存兜底存储中的过期项（至多每 60s 一次），防长期运行内存膨胀。"""
        now = time.time()
        if now - self._last_purge < 60:
            return
        self._last_purge = now
        for k in [k for k, v in _memory_store.items() if v[0] <= now]:
            _memory_store.pop(k, None)
        for k in [k for k, (_, exp) in _memory_counter.items() if exp <= now]:
            _memory_counter.pop(k, None)
        # 限流 key 按 ip+日 逐日新增，过期 key 不清扫会永久驻留
        for k in [k for k, ts in _memory_rate.items() if not ts or max(ts) <= now - 86400]:
            _memory_rate.pop(k, None)

    async def get_json(self, key: str) -> dict | None:
        key = _norm_key(key)
        r = await self._get_redis()
        if r:
            val = await r.get(key)
            return json.loads(val) if val else None
        self._purge_memory()
        item = _memory_store.get(key)
        if item and item[0] > time.time():
            return json.loads(item[1])
        return None

    async def set_json(self, key: str, data: dict, ttl: int):
        key = _norm_key(key)
        r = await self._get_redis()
        payload = json.dumps(data, ensure_ascii=False)
        if r:
            await r.setex(key, ttl, payload)
        else:
            self._purge_memory()
            _memory_store[key] = (time.time() + ttl, payload)

    async def check_rate(self, ip: str) -> tuple[bool, int]:
        """返回 (允许, 剩余次数)。按自然日计数。"""
        day = time.strftime("%Y%m%d")
        key = _norm_key(f"ratelimit:{ip}:{day}")
        r = await self._get_redis()
        if r:
            cnt = await r.incr(key)
            if cnt == 1:
                await r.expire(key, 86400)
            return cnt <= settings.rate_limit_daily, max(0, settings.rate_limit_daily - cnt)
        self._purge_memory()
        _memory_rate[key] = [c for c in _memory_rate[key] if c > time.time() - 86400]
        _memory_rate[key].append(time.time())
        cnt = len(_memory_rate[key])
        return cnt <= settings.rate_limit_daily, max(0, settings.rate_limit_daily - cnt)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        """计数器（首次写入设置 TTL），用于登录失败锁定/短信频控。返回当前计数。"""
        key = _norm_key(key)
        r = await self._get_redis()
        if r:
            cnt = await r.incr(key)
            if cnt == 1:
                await r.expire(key, ttl)
            return int(cnt)
        self._purge_memory()
        now = time.time()
        item = _memory_counter.get(key)
        if not item or item[1] < now:
            _memory_counter[key] = (1, now + ttl)
            return 1
        _memory_counter[key] = (item[0] + 1, item[1])
        return item[0] + 1

    async def delete(self, key: str) -> None:
        """删除单个 key（如登录成功后清除失败计数）。"""
        key = _norm_key(key)
        r = await self._get_redis()
        if r:
            await r.delete(key)
        else:
            _memory_store.pop(key, None)
            _memory_counter.pop(key, None)
            _memory_rate.pop(key, None)

    async def health(self) -> str:
        """探活（O-8）：ok = Redis 正常；degraded = 降级内存模式（业务仍可用）。"""
        try:
            r = await self._get_redis()
            if r is not None:
                await r.ping()
                return "ok"
        except Exception:  # noqa: BLE001
            pass
        return "degraded"


cache = CacheService()
