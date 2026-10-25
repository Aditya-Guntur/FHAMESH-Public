# Quick Start

Get FHAMESH running in under 5 minutes.

## Prerequisites

- **Python 3.12+** (required)
- **Git** (to clone the repository)
- Redis is NOT required for tests -- the test suite uses `fakeredis`

## Installation

Clone the repository and install in development mode:

```bash
git clone https://github.com/Aditya-Guntur/Federated.git
cd Federated
pip install -e ".[dev]"
```

!!! warning "Use `.[dev]` not just `.`"
    The `[dev]` extra includes test dependencies like `fakeredis`, `pytest`, and `pytest-asyncio`. If you install with just `pip install -e .`, tests will fail with import errors.

## Running Tests

Run the full test suite (116 tests, no Redis needed):

```bash
pytest
```

For verbose output showing every test name:

```bash
pytest -v
```

All tests use `fakeredis` as an in-memory Redis substitute. No external services are required.

## CLI Commands

FHAMESH provides a CLI entry point via the `fhamesh` command:

```bash
# Start the full mesh (requires Redis on localhost:6379)
fhamesh run

# Run the demo walkthrough
fhamesh demo

# Interactive query mode
fhamesh interactive

# Health check
fhamesh health
```

!!! tip "If `fhamesh` is not found"
    If the `fhamesh` command is not on your PATH after installation, use the module entry point instead:

    ```bash
    python -m fhamesh.runner run
    python -m fhamesh.runner demo
    python -m fhamesh.runner interactive
    python -m fhamesh.runner health
    ```

## Building the Documentation

Install documentation dependencies and serve locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

The docs will be available at `http://127.0.0.1:8000`.

## Troubleshooting

### `ModuleNotFoundError: No module named 'fakeredis'`

You installed without the dev extras. Reinstall:

```bash
pip install -e ".[dev]"
```

### `fhamesh: command not found`

The CLI entry point was not installed on your PATH. Use the module entry point:

```bash
python -m fhamesh.runner run
```

### Redis connection errors during `fhamesh run`

The `run`, `demo`, and `interactive` commands require a running Redis instance on `localhost:6379`. Install and start Redis, or use Docker:

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

Tests do NOT require Redis -- they use `fakeredis`.

### Tests pass but `fhamesh run` fails

This is expected if Redis is not running. The test suite is self-contained with `fakeredis`. The `run` command needs a real Redis instance for inter-agent communication.

## Next Steps

- [Architecture](architecture.md) -- Understand the three-layer design
- [Security Overview](security/overview.md) -- Learn about the zero trust model
- [Tutorials](tutorials/input-sanitization.md) -- Walk through every component hands-on
