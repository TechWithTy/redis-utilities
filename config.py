"""
Redis configuration settings with timeout and performance parameters.
"""


from redis.exceptions import ConnectionError, ResponseError, TimeoutError


class RedisConfig:
    # Sharding configuration
    REDIS_SHARD_SIZE = 25 * 1024 * 1024 * 1024  # 25GB
    REDIS_SHARD_OPS_LIMIT = 25000  # ops/second
    REDIS_SHARD_NODES = [
        {"host": "shard1", "port": 6379},
        {"host": "shard2", "port": 6379}
    ]

    # Connection timeout in seconds (float)
    REDIS_TIMEOUT = 5.0

    # Circuit breaker settings
    CIRCUIT_BREAKER = {
        'failure_threshold': 3,  # Failures before opening
        'recovery_timeout': 30,  # Seconds to wait before attempting recovery
        'expected_exceptions': (
            ConnectionError,
            TimeoutError,
            ResponseError
        )
    }

    # Monitoring settings
    METRICS_UPDATE_INTERVAL = 60  # Seconds between metrics updates

    # Connection pool settings
    REDIS_MAX_CONNECTIONS = 100
    REDIS_IDLE_TIMEOUT = 300  # seconds

    # Performance tuning
    REDIS_SOCKET_TIMEOUT = 10.0
    REDIS_SOCKET_CONNECT_TIMEOUT = 5.0

    # Retry configuration
    REDIS_RETRY_ATTEMPTS = 3
    REDIS_RETRY_DELAY = 0.1  # seconds

    # Health check interval in seconds
    REDIS_HEALTH_CHECK_INTERVAL = 60

    # Cache-specific settings
    REDIS_CACHE_TTL = 3600  # Default TTL in seconds (1 hour)
    REDIS_CACHE_PREFIX = "lead_ignite:"

    # Rate limiting settings
    REDIS_RATE_LIMIT_WINDOW = 60  # seconds
    REDIS_RATE_LIMIT_MAX_REQUESTS = 100
