"""cache.py 单测：内存降级模式的读写/清扫/计数器（不依赖 Redis，自动降级）

直写内存 dict 时必须用 _norm_key 规范化后的 key（与函数内部一致），
否则读写到的不是同一个条目。
"""
import asyncio
import time

from app.services import cache as cache_mod
from app.services.cache import _norm_key, cache


def _reset():
    """每个用例独立状态：清空内存存储 + 归零清扫节流。"""
    cache_mod._memory_store.clear()
    cache_mod._memory_rate.clear()
    cache_mod._memory_counter.clear()
    cache._last_purge = 0.0
    cache._redis = None
    cache._degraded_at = None


def test_memory_set_get_roundtrip():
    _reset()
    asyncio.run(cache.set_json("k", {"x": 1}, 60))
    assert asyncio.run(cache.get_json("k")) == {"x": 1}


def test_memory_expiry():
    _reset()
    cache_mod._memory_store[_norm_key("k")] = (time.time() - 1, '{"x": 1}')  # 已过期
    assert asyncio.run(cache.get_json("k")) is None


def test_purge_removes_expired_keeps_alive():
    _reset()
    now = time.time()
    cache_mod._memory_store["dead"] = (now - 10, "{}")
    cache_mod._memory_store["alive"] = (now + 999, "{}")
    cache_mod._memory_rate["deadrate"] = [now - 100000]
    cache_mod._memory_counter["deadcnt"] = (5, now - 10)
    asyncio.run(cache.set_json("k", {}, 60))  # 触发清扫（_last_purge 已归零）
    assert "dead" not in cache_mod._memory_store
    assert "alive" in cache_mod._memory_store
    assert "deadrate" not in cache_mod._memory_rate
    assert "deadcnt" not in cache_mod._memory_counter


def test_incr_with_ttl_counts_and_expires():
    _reset()
    assert asyncio.run(cache.incr_with_ttl("cnt", 100)) == 1
    assert asyncio.run(cache.incr_with_ttl("cnt", 100)) == 2
    # 模拟过期后重新计数
    cache_mod._memory_counter[_norm_key("cnt")] = (2, time.time() - 1)
    assert asyncio.run(cache.incr_with_ttl("cnt", 100)) == 1


def test_delete_clears_all_names():
    _reset()
    asyncio.run(cache.set_json("k", {}, 60))
    asyncio.run(cache.incr_with_ttl("k", 60))
    asyncio.run(cache.delete("k"))
    assert asyncio.run(cache.get_json("k")) is None
    assert _norm_key("k") not in cache_mod._memory_counter


def test_degraded_cooldown_retry():
    _reset()
    # 模拟已在降级冷却中：60s 内不再尝试连接（保持降级）
    cache._degraded_at = time.time()
    assert asyncio.run(cache._get_redis()) is None
    # 冷却期过后应重新尝试（本机无 Redis 会再次降级并刷新时间戳）
    cache._degraded_at = time.time() - cache.DEGRADED_RETRY_SECONDS - 1
    asyncio.run(cache.get_json("anything"))
    assert cache._degraded_at is not None  # 重试失败 → 重新进入冷却
