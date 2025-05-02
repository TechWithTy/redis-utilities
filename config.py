"""
Redis configuration settings with timeout and performance parameters.
"""


class RedisConfig:
    # Connection timeout in seconds (float)
    REDIS_TIMEOUT = 5.0

    # Circuit breaker failure threshold (number of failures before opening)
    REDIS_FAILURE_THRESHOLD = 3

    # Circuit breaker recovery timeout in seconds
    REDIS_RECOVERY_TIMEOUT = 30

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
