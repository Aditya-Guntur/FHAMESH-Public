"""LangGraph-backed reasoning agents for fhamesh.

Replaces the keyword/regex "intelligence" in the leaf and orchestrator
layers with real agent orchestration: small, stateful graphs that
reason over an LLM and fall back to the deterministic implementation
when the model is unreachable.

This package is optional. Install it with `pip install -e ".[agents]"`.
Everything that imports from here guards against the dependency being
absent and degrades to the regex/rule-based backend instead.
"""
