# API Reference: Orchestrator

The `fhamesh.orchestrator` package implements the logic layer: credential verification, uncertainty estimation, query decomposition, subtree management, peer mesh, and policy enforcement.

## OrchestratorNode

Top-level orchestrator agent that composes verification, uncertainty, policy, and decomposition into a single pipeline.

::: fhamesh.orchestrator.controller.OrchestratorNode

## UncertaintyEstimator

Scores intents across 4 anomaly dimensions (parameter plausibility, domain-action consistency, confidence calibration, category coherence) to detect adversarial inputs.

::: fhamesh.orchestrator.uncertainty.UncertaintyEstimator

## UncertaintyResult

Result of uncertainty estimation, containing anomaly scores, adversarial flag, and reasoning.

::: fhamesh.orchestrator.uncertainty.UncertaintyResult

## SubtreeManager

Manages the lifecycle of spawned subtrees with configurable timeout and maximum depth.

::: fhamesh.orchestrator.subtree.SubtreeManager

## PeerMesh

Enables peer-to-peer communication between orchestrator nodes for distributed coordination.

::: fhamesh.orchestrator.mesh.PeerMesh

## QueryDecomposer

Breaks complex queries into sub-queries that can be routed to different data core nodes or executed in parallel.

::: fhamesh.orchestrator.decomposer.QueryDecomposer

## ResultAggregator

Aggregates results from multiple sub-queries back into a single response.

::: fhamesh.orchestrator.aggregator.ResultAggregator

## ExecutionPathValidator

Validates structural integrity of incoming requests at the orchestrator layer, including sanitization checks, eligibility gate passage, subtree depth limits, and correlation chain validity.

::: fhamesh.orchestrator.validator.ExecutionPathValidator
