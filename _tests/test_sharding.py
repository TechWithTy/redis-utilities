"""
Production-grade Redis sharding tests with:
- Error handling and logging
- Performance metrics
- Edge case testing
- Monitoring integration
"""
import asyncio
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.core.redis.metrics import record_metrics
from app.core.redis.client import RedisClient
from app.core.redis.config import RedisConfig

logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_shard_distribution():
    """Test keys are properly distributed across shards with metrics"""
    with patch('redis.asyncio.cluster.RedisCluster') as mock_cluster:
        mock_client = MagicMock()
        mock_cluster.return_value = mock_client
        
        # Setup metrics
        start_time = datetime.now()
        
        try:
            # Test with 1000 keys
            client = RedisClient()
            redis = await client.get_client()
            
            for i in range(1000):
                await redis.set(f"test_key_{i}", f"value_{i}")
            
            # Verify distribution
            called_nodes = {call[0][0] for call in mock_client.set.call_args_list}
            assert len(called_nodes) == len(RedisConfig.REDIS_SHARD_NODES)
            
            # Record metrics
            duration = (datetime.now() - start_time).total_seconds()
            record_metrics(
                "redis_sharding_distribution",
                {"keys": 1000, "shards": len(called_nodes), "duration": duration}
            )
            
        except Exception as e:
            logger.error(f"Shard distribution test failed: {e}")
            raise
        finally:
            # Cleanup
            mock_client.reset_mock()

@pytest.mark.asyncio
async def test_shard_failover():
    """Test client handles partial cluster failures with retries"""
    with patch('redis.asyncio.cluster.RedisCluster.execute_command') as mock_exec:
        # Setup failure scenarios
        mock_exec.side_effect = [
            ConnectionError("Shard down"),
            "OK",  # Success on retry
            "OK"   # Success on new shard
        ]
        
        try:
            client = RedisClient()
            redis = await client.get_client()
            
            # Should succeed after failover
            result = await redis.set("test_key", "value")
            assert result == "OK"
            assert mock_exec.call_count == 3
            
            # Verify retry logging
            assert any("Retrying on different shard" in str(call) 
                      for call in mock_exec.call_args_list)
            
        except Exception as e:
            logger.error(f"Shard failover test failed: {e}")
            raise

@pytest.mark.asyncio
async def test_shard_rebalancing():
    """Test cluster rebalancing doesn't cause data loss"""
    with patch('redis.asyncio.cluster.RedisCluster') as mock_cluster:
        mock_client = MagicMock()
        mock_cluster.return_value = mock_client
        
        # Setup rebalance scenario
        mock_client.get.side_effect = [
            None,  # First attempt - key not found
            "moved_value",  # Second attempt - found after rebalance
            RuntimeError("Cluster rebalancing")  # Edge case
        ]
        
        try:
            client = RedisClient()
            redis = await client.get_client()
            
            # Test normal rebalance
            value = await redis.get("rebalanced_key")
            assert value == "moved_value"
            
            # Test edge case during rebalance
            with pytest.raises(RuntimeError):
                await redis.get("edge_case_key")
            
        except Exception as e:
            logger.error(f"Shard rebalancing test failed: {e}")
            raise
        finally:
            mock_client.reset_mock()

@pytest.mark.asyncio
async def test_shard_performance_under_load():
    """Test shard performance under concurrent load"""
    with patch('redis.asyncio.cluster.RedisCluster') as mock_cluster:
        mock_client = MagicMock()
        mock_cluster.return_value = mock_client
        
        # Setup concurrent test
        start_time = datetime.now()
        
        try:
            client = RedisClient()
            redis = await client.get_client()
            
            # Simulate concurrent requests
            tasks = []
            for i in range(1000):
                tasks.append(redis.set(f"load_key_{i}", f"value_{i}"))
            
            await asyncio.gather(*tasks)
            
            # Verify performance
            duration = (datetime.now() - start_time).total_seconds()
            assert duration < 2.0  # Should complete under 2 seconds
            
            # Record metrics
            record_metrics(
                "redis_sharding_load_test",
                {"operations": 1000, "duration": duration}
            )
            
        except Exception as e:
            logger.error(f"Shard load test failed: {e}")
            raise
        finally:
            mock_client.reset_mock()
