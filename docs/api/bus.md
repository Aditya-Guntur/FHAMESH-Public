# API Reference: Bus & Transport

The `fhamesh.bus` package provides the inter-agent communication layer using Redis pub/sub.

## RedisTransport

Pub/sub transport layer using Redis. Handles serialization, channel subscription, and message delivery between agents.

::: fhamesh.bus.transport.RedisTransport

## ChannelRouter

Maps agent IDs and domains to Redis pub/sub channels. Determines which channel a message should be published to based on the target agent's layer and domain.

::: fhamesh.bus.channels.ChannelRouter

## MessageMiddleware

Middleware pipeline for message processing. Intercepts messages before delivery for logging, validation, or transformation.

::: fhamesh.bus.middleware.MessageMiddleware

!!! note "fakeredis for testing"
    The test suite uses `fakeredis` as an in-memory Redis substitute. No running Redis instance is needed for tests. The `RedisTransport` accepts any Redis-compatible client, including `fakeredis.aioFakeRedis`.
