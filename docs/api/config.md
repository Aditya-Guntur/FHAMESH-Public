# API Reference: Config

The `fhamesh.config` package handles loading and validating YAML configuration files using Pydantic schemas.

## ConfigLoader

Loads and merges YAML configuration files from the `config/` directory. Provides typed access to all configuration sections.

::: fhamesh.config.loader.ConfigLoader

## SystemConfig

Pydantic model for the `system` section of `config/default.yaml`.

::: fhamesh.config.schemas.SystemConfig

## SecurityConfig

Pydantic model for the `security` section of `config/default.yaml`. Includes signing keys and token TTL.

::: fhamesh.config.schemas.SecurityConfig

## RedisConfig

Pydantic model for the `redis` section of `config/default.yaml`.

::: fhamesh.config.schemas.RedisConfig

## PrivacyConfig

Pydantic model for `config/privacy.yaml`. Includes differential privacy parameters and PII masking strategies.

::: fhamesh.config.schemas.PrivacyConfig

!!! tip "Configuration files"
    See the [Configuration Reference](../guides/configuration.md) for a complete guide to all four YAML configuration files and their parameters.
