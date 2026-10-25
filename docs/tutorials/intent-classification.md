# Tutorial: Intent Classification

The `IntentClassifier` maps natural language queries to structured `IntentDescriptor` objects containing the domain, category, action, and confidence score. The default classifier uses keyword/regex matching -- you can replace it with an ML model by subclassing `BaseClassifier`.

## Code Example

```python
from fhamesh.leaf.classifier import IntentClassifier

classifier = IntentClassifier()

queries = [
    "Show me employee salaries in engineering",
    "What is the average product price?",
    "List all orders above 500",
    "Delete all records from employees",
    "Navigate to the finance dashboard",
    "Update employee John salary to 100000",
]

for q in queries:
    intent = classifier.classify(q)
    print(f'"{q}"')
    print(f"  Domain: {intent.domain}, Category: {intent.category}, "
          f"Action: {intent.action}, Confidence: {intent.confidence}")
```

## Expected Output

```
"Show me employee salaries in engineering"
  Domain: hr, Category: navigation, Action: lookup_salary, Confidence: 0.7

"What is the average product price?"
  Domain: product, Category: query, Action: lookup_product, Confidence: 0.7

"List all orders above 500"
  Domain: finance, Category: query, Action: lookup, Confidence: 0.6

"Delete all records from employees"
  Domain: hr, Category: command, Action: lookup, Confidence: 0.6

"Navigate to the finance dashboard"
  Domain: general, Category: navigation, Action: general_query, Confidence: 0.3

"Update employee John salary to 100000"
  Domain: hr, Category: command, Action: lookup_salary, Confidence: 0.7
```

## Explanation

The classifier determines three aspects of each query:

**Domain** is detected from keywords:

- "salary", "employee" --> `hr`
- "product", "price" --> `product`
- "order" --> `finance`
- No strong match --> `general`

**Category** is detected from verbs:

- "show", "navigate" --> `navigation`
- "what", "list" --> `query`
- "delete", "update" --> `command`

**Action** is inferred from context. For example, "salary" in an HR query maps to `lookup_salary`.

**Confidence** reflects how many keyword matches were found. Queries with multiple strong signals (like "employee salaries") get higher confidence (0.7) than vague queries like "navigate to the finance dashboard" (0.3).

!!! note "Pluggable classifiers"
    The default keyword-based classifier is suitable for development and testing. For production, subclass `BaseClassifier` and plug in your own ML model. See the [Extending the Framework](../guides/extending.md) guide.
