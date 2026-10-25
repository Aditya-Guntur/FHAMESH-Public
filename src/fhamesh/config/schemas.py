"""Pydantic models for configuration validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379"
    session_ttl_seconds: int = 60


class SigningKeysConfig(BaseModel):
    leaf: str = "default_leaf_signing_key_change_me!"
    orchestrator: str = "default_orch_signing_key_change_me!"
    datacore: str = "default_core_signing_key_change_me!"


class SecurityConfig(BaseModel):
    token_ttl_seconds: int = 30
    max_hops: int = 10
    signing_keys: SigningKeysConfig = SigningKeysConfig()


class SanitizerConfig(BaseModel):
    max_length: int = 2000


class ClassifierConfig(BaseModel):
    min_confidence: float = 0.3


class EligibilityConfig(BaseModel):
    min_confidence: float = 0.3


class LeafConfig(BaseModel):
    sanitizer: SanitizerConfig = SanitizerConfig()
    classifier: ClassifierConfig = ClassifierConfig()
    eligibility: EligibilityConfig = EligibilityConfig()


class ValidationConfig(BaseModel):
    max_subtree_depth: int = 5


class UncertaintyConfig(BaseModel):
    rejection_threshold: float = 0.2
    adversarial_threshold: float = 0.8


class SubtreeConfig(BaseModel):
    timeout_seconds: float = 30.0


class OrchestratorConfig(BaseModel):
    validation: ValidationConfig = ValidationConfig()
    uncertainty: UncertaintyConfig = UncertaintyConfig()
    subtree: SubtreeConfig = SubtreeConfig()


class QueryValidationConfig(BaseModel):
    require_justification: bool = True
    allowed_tables: list[str] = Field(default_factory=lambda: ["employees", "products", "orders"])


class DataCoreConfig(BaseModel):
    db_path: str = "data.db"
    query_validation: QueryValidationConfig = QueryValidationConfig()


class AuditConfig(BaseModel):
    db_path: str = "audit.db"


class DifferentialPrivacyConfig(BaseModel):
    default_epsilon: float = 1.0
    max_budget_per_user: float = 10.0
    budget_reset_interval_hours: int = 24
    field_sensitivity: dict[str, float] = Field(default_factory=lambda: {
        "salary": 50000.0,
        "age": 1.0,
        "order_amount": 1000.0,
        "count": 1.0,
    })


class PIIConfig(BaseModel):
    mask_fields: dict[str, str] = Field(default_factory=lambda: {
        "ssn": "last4",
        "email": "email_domain",
        "phone": "full",
    })
    detect_patterns: bool = True


class PrivacyConfig(BaseModel):
    differential_privacy: DifferentialPrivacyConfig = DifferentialPrivacyConfig()
    pii: PIIConfig = PIIConfig()


class PermissionEntry(BaseModel):
    resource: str
    action: str
    fields: list[str] = Field(default_factory=list)


class RoleConfig(BaseModel):
    permissions: list[PermissionEntry] = Field(default_factory=list)
    max_query_depth: int = 3
    rate_limit_per_minute: int = 60


class RateLimitConfig(BaseModel):
    requests_per_minute: int = 100
    burst: int = 20


class RateLimitsConfig(BaseModel):
    global_limit: RateLimitConfig = Field(default=RateLimitConfig(), alias="global")
    per_user: RateLimitConfig = Field(default=RateLimitConfig(requests_per_minute=30, burst=10))

    model_config = {"populate_by_name": True}


class PoliciesConfig(BaseModel):
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    rate_limits: RateLimitsConfig = RateLimitsConfig()


class DomainEntry(BaseModel):
    description: str = ""
    intent_patterns: list[str] = Field(default_factory=list)
    orchestrator_domain: str = "general"
    datacore_tables: list[str] = Field(default_factory=list)


class DomainsConfig(BaseModel):
    domains: dict[str, DomainEntry] = Field(default_factory=dict)


class SystemInfo(BaseModel):
    name: str = "fhamesh"
    log_level: str = "INFO"


class SystemConfig(BaseModel):
    """Top-level configuration model."""
    system: SystemInfo = SystemInfo()
    redis: RedisConfig = RedisConfig()
    security: SecurityConfig = SecurityConfig()
    leaf: LeafConfig = LeafConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()
    datacore: DataCoreConfig = DataCoreConfig()
    audit: AuditConfig = AuditConfig()
    policies: PoliciesConfig = PoliciesConfig()
    privacy: PrivacyConfig = PrivacyConfig()
    domains: DomainsConfig = DomainsConfig()
