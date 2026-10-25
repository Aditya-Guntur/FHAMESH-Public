# API Reference: Leaf Layer

The `fhamesh.leaf` package implements the edge layer of the mesh: input sanitization, intent classification, domain routing, and eligibility gating.

## InputSanitizer

Runs 16+ compiled regex patterns against user input. Blocks SQL injection, XSS, prompt injection, path traversal, and command injection.

::: fhamesh.leaf.sanitizer.InputSanitizer

## BaseClassifier

Abstract base class for intent classifiers. Subclass this to plug in your own ML model.

::: fhamesh.leaf.classifier.BaseClassifier

## IntentClassifier

Default keyword/regex-based intent classifier. Maps natural language to `IntentDescriptor` objects.

::: fhamesh.leaf.classifier.IntentClassifier

## DomainRouter

Routes classified intents to the correct orchestrator based on domain definitions from `config/domains.yaml`.

::: fhamesh.leaf.router.DomainRouter

## EligibilityGate

Final check before a message leaves the leaf layer. Validates authentication, domain, action, and confidence threshold.

::: fhamesh.leaf.gate.EligibilityGate

## LeafNode

Top-level leaf agent that composes the sanitizer, classifier, router, and gate into a single processing pipeline.

::: fhamesh.leaf.node.LeafNode
