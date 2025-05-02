"""
Tests for the Redis client's built-in circuit breaker functionality
"""

import time
import logging
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from redis.exceptions import ConnectionError, ResponseError
from circuitbreaker import CircuitBreakerError

from app.core.redis.client import RedisClient
from app.core.redis.config import RedisConfig

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def reset_prometheus():
    """Reset Prometheus metrics between tests"""
    for collector in list(REGISTRY._collector_to_names):
        if collector not in REGISTRY._names_to_collectors.values():
            REGISTRY.unregister(collector)


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold():
    """Verify client's circuit opens after configured failures"""
    client = RedisClient()

    with patch("redis.asyncio.cluster.RedisCluster.execute_command") as mock_exec:
        mock_exec.side_effect = ConnectionError("Shard down")

        # Should fail within threshold
        for _ in range(RedisConfig.CIRCUIT_BREAKER["failure_threshold"] - 1):
            with pytest.raises(ConnectionError):
                await client.get("test_key")

        # Next failure should open circuit
        with pytest.raises(CircuitBreakerError):
            await client.get("test_key")


@pytest.mark.asyncio
async def test_circuit_resets_after_timeout():
    """Test client's automatic recovery after timeout"""
    client = RedisClient()

    with (
        patch("time.time", return_value=0),
        patch("redis.asyncio.cluster.RedisCluster.execute_command") as mock_exec,
    ):
        mock_exec.side_effect = ConnectionError("Shard down")

        # Open circuit
        for _ in range(RedisConfig.CIRCUIT_BREAKER["failure_threshold"]):
            with pytest.raises(ConnectionError):
                await client.get("test_key")

        # Fast forward past recovery timeout
        with patch(
            "time.time",
            return_value=RedisConfig.CIRCUIT_BREAKER["recovery_timeout"] + 1,
        ):
            mock_exec.return_value = "OK"
            result = await client.get("test_key")
            assert result == "OK"


@pytest.mark.asyncio
async def test_error_classification():
    """Verify client handles different error types properly"""
    client = RedisClient()

    test_cases = [
        (ConnectionError("Timeout"), "connection"),
        (ResponseError("READONLY"), "response"),
    ]

    for error, error_type in test_cases:
        with patch("redis.asyncio.cluster.RedisCluster.execute_command") as mock_exec:
            mock_exec.side_effect = error
            with pytest.raises(type(error)):
                await client.get("test_key")


@pytest.mark.asyncio
async def test_metrics_collection():
    """Verify client collects proper circuit metrics"""
    client = RedisClient()

    with patch("redis.asyncio.cluster.RedisCluster.execute_command") as mock_exec:
        mock_exec.side_effect = ConnectionError("Shard down")

        try:
            await client.get("test_key")
        except ConnectionError:
            pass

        # Verify metrics were updated
        assert (
            client._metrics["errors"]
            .labels(operation="get", type="connection")
            ._value.get()
            == 1
        )
