# Redis Rate Limiter Test Strategy

## Context

This document describes the test logic and rationale for the suite of Redis-backed rate limiting algorithms in `test_algorithms.py`.

## Key Fixes (May 2025)

- **Test Isolation:** Each test flushes Redis before running to ensure no state leakage between tests.
- **Test Logic Updated:**
  - **Fixed Window, Sliding Window, Token Bucket:**
    - The first two calls are allowed (limit=2).
    - The third call is blocked.
    - After waiting for the window/interval, the next call is allowed again.
  - **Throttle, Debounce:**
    - Only the first call is allowed per interval.
    - Subsequent calls within the interval are blocked.
    - After waiting for the interval, the next call is allowed again.
- **Fail-Open Guarantee:** If Redis is unavailable, all algorithms should allow requests (fail-open), and this is explicitly tested.

## Example Test Pattern

```
# For limit=2
allowed1 = await algo_func(...)
assert allowed1 is True
allowed2 = await algo_func(...)
assert allowed2 is True
allowed3 = await algo_func(...)
assert allowed3 is False
await asyncio.sleep(window)
allowed4 = await algo_func(...)
assert allowed4 is True
```

## Rationale

- Ensures the algorithms match their contract and are robust against Redis failures.
- Prevents false positives/negatives due to state leakage or incorrect test logic.

## See Also
- `conftest.py` for the Redis flush fixture
- Each algorithm's implementation for details on logic and edge cases
