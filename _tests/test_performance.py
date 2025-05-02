"""
Production-grade Redis performance tests with:
- Comprehensive metrics using Prometheus
- Failover scenario testing
- Circuit breaker integration
- Performance benchmarking
"""

import asyncio
import logging
import time
from datetime import datetime
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, Counter, Gauge, Histogram

from app.core.redis.client import RedisClient

logger = logging.getLogger(__name__)

# Prometheus metrics
REDIS_OPS_METRICS = {
    "throughput": Gauge("redis_ops_per_sec", "Operations per second", ["operation"]),
    "latency": Histogram(
        "redis_op_latency",
        "Operation latency seconds",
        ["operation"],
        buckets=[0.001, 0.01, 0.1, 0.5],
    ),
    "errors": Counter("redis_op_errors", "Operation errors", ["operation", "type"]),
}


@pytest.fixture(autouse=True)
def reset_prometheus():
    """Reset Prometheus metrics between tests"""
    for collector in list(REGISTRY._collector_to_names):
        if collector not in REGISTRY._names_to_collectors.values():
            REGISTRY.unregister(collector)


@pytest.mark.asyncio
async def test_failover_scenarios():
    """Test performance during failover scenarios"""
    client = RedisClient()

    with patch("redis.asyncio.cluster.RedisCluster.execute_command") as mock_exec:
        # Simulate intermittent failures
        mock_exec.side_effect = [
            Exception("Node down"),
            "OK",
            Exception("Cluster reconfigured"),
            "OK",
        ]

        start = time.time()
        try:
            await client.set("failover_key", "value")
            REDIS_OPS_METRICS["errors"].labels(operation="set", type="failover").inc()
        except Exception:
            pass

        # Should recover and succeed
        assert await client.set("failover_key", "value") == "OK"

        latency = time.time() - start
        REDIS_OPS_METRICS["latency"].labels(operation="failover").observe(latency)


@pytest.mark.asyncio
async def test_circuit_breaker_performance():
    """Test performance with circuit breaker engaged"""
    client = RedisClient()

    with patch(
        "app.core.redis.circuit_breaker.CircuitBreaker.is_open", return_value=True
    ):
        start = time.time()
        try:
            await client.set("cb_key", "value")
        except Exception as e:
            REDIS_OPS_METRICS["errors"].labels(
                operation="set", type="circuit_breaker"
            ).inc()
            latency = time.time() - start
            REDIS_OPS_METRICS["latency"].labels(operation="circuit_breaker").observe(
                latency
            )


@pytest.mark.asyncio
async def test_throughput_under_stress():
    """Measure throughput under simulated stress"""
    client = RedisClient()
    ops = 0
    start = time.time()

    while time.time() - start < 5:  # Run for 5 seconds
        try:
            await client.set(f"stress_{ops}", "value")
            ops += 1
        except Exception as e:
            REDIS_OPS_METRICS["errors"].labels(operation="set", type="stress").inc()

    throughput = ops / (time.time() - start)
    REDIS_OPS_METRICS["throughput"].labels(operation="set").set(throughput)

    assert throughput > 5000  # Minimum ops/sec threshold


@pytest.mark.asyncio
async def test_latency_distribution():
    """Measure latency distribution under load"""
    client = RedisClient()
    latencies = []

    for i in range(100):
        start = time.time()
        await client.set(f"latency_{i}", "value")
        latency = time.time() - start
        latencies.append(latency)
        REDIS_OPS_METRICS["latency"].labels(operation="set").observe(latency)

    avg = sum(latencies) / len(latencies)
    assert avg < 0.01  # 10ms avg latency threshold
