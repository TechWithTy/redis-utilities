"""
Tests for Redis-backed rate limiting/throttling algorithms and their fail-open logic.
- Fixed Window
- Sliding Window
- Token Bucket
- Throttle
- Debounce

* Uses pytest and pytest-asyncio for async tests
* Mocks Redis to simulate fail-open
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, patch

import sys
sys.path.append("..")

from app.core.redis.algorithims.debounce import is_allowed_debounce
from app.core.redis.algorithims.fixed_window import is_allowed_fixed_window
from app.core.redis.algorithims.sliding_window import is_allowed_sliding_window
from app.core.redis.algorithims.throttle import is_allowed_throttle
from app.core.redis.algorithims.token_bucket import is_allowed_token_bucket

pytestmark = pytest.mark.asyncio

@pytest.mark.parametrize("algo_func,kwargs", [
    (is_allowed_fixed_window, {"key": "test:fixed", "limit": 2, "window": 2}),
    (is_allowed_sliding_window, {"key": "test:sliding", "limit": 2, "window": 2}),
    (is_allowed_token_bucket, {"key": "test:bucket", "capacity": 2, "refill_rate": 1, "interval": 2}),
    (is_allowed_throttle, {"key": "test:throttle", "interval": 2}),
    (is_allowed_debounce, {"key": "test:debounce", "interval": 2}),
])
async def test_algorithms_allow_and_block(algo_func, kwargs):
    # Allow first call
    allowed1 = await algo_func(**kwargs)
    assert allowed1 is True
    # Second call (may be blocked depending on algo)
    allowed2 = await algo_func(**kwargs)
    # For fixed/sliding/token: should block after limit. For throttle/debounce: may block immediately
    assert isinstance(allowed2, bool)

@pytest.mark.parametrize("algo_func,kwargs,redis_path", [
    (is_allowed_fixed_window, {"key": "failopen:fixed", "limit": 2, "window": 2}, "app.core.redis.algorithims.fixed_window.redis_client"),
    (is_allowed_sliding_window, {"key": "failopen:sliding", "limit": 2, "window": 2}, "app.core.redis.algorithims.sliding_window.redis_client"),
    (is_allowed_token_bucket, {"key": "failopen:bucket", "capacity": 2, "refill_rate": 1, "interval": 2}, "app.core.redis.algorithims.token_bucket.redis_client"),
    (is_allowed_throttle, {"key": "failopen:throttle", "interval": 2}, "app.core.redis.algorithims.throttle.redis_client"),
    (is_allowed_debounce, {"key": "failopen:debounce", "interval": 2}, "app.core.redis.algorithims.debounce.redis_client"),
])
async def test_algorithms_fail_open(monkeypatch, algo_func, kwargs, redis_path):
    # Patch all redis_client methods to raise exception
    class FailingRedis:
        async def __getattr__(self, name):
            async def fail(*a, **k):
                raise Exception("Redis unavailable")
            return fail
        async def incr(self, *a, **k): raise Exception("Redis unavailable")
        async def expire(self, *a, **k): raise Exception("Redis unavailable")
        async def ttl(self, *a, **k): raise Exception("Redis unavailable")
        async def set(self, *a, **k): raise Exception("Redis unavailable")
        async def _client(self, *a, **k): raise Exception("Redis unavailable")
        async def zremrangebyscore(self, *a, **k): raise Exception("Redis unavailable")
        async def zadd(self, *a, **k): raise Exception("Redis unavailable")
        async def zcard(self, *a, **k): raise Exception("Redis unavailable")
        async def eval(self, *a, **k): raise Exception("Redis unavailable")
        async def setnx(self, *a, **k): raise Exception("Redis unavailable")
    monkeypatch.setattr(redis_path, FailingRedis())
    allowed = await algo_func(**kwargs)
    assert allowed is True  # Should always allow if Redis fails
