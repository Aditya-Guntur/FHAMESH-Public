"""FHAMESH — Federated Hierarchical Agent Mesh with Zero Trust Orchestration.

A pluggable Python framework for building secure, distributed agent systems.
"""

__version__ = "0.1.0"

from .core.agent import BaseAgent
from .core.message import IntentDescriptor, MessageEnvelope, QueryResult
from .core.types import AgentLayer, MessageType
from .core.errors import FHAMeshError
