"""Tool foundation for 3.4: specs, strict schemas, approvals and one broker."""

from __future__ import annotations

from .approvals import APPROVALS_SCHEMA, ApprovalError, ApprovalStore
from .broker import (DEFAULT_MAX_RESULT_CHARS, DEFAULT_TOKEN_TTL, PROVIDER_KINDS,
                     ToolBroker, ToolCall, ToolContext, ToolDenied, ToolResult,
                     ToolSpec, approval_hash_for, as_quoted_block)
from .schema import SchemaError, canonical_json, validate_arguments, validate_schema

__all__ = [
    "APPROVALS_SCHEMA",
    "ApprovalError",
    "ApprovalStore",
    "DEFAULT_MAX_RESULT_CHARS",
    "DEFAULT_TOKEN_TTL",
    "PROVIDER_KINDS",
    "SchemaError",
    "ToolBroker",
    "ToolCall",
    "ToolContext",
    "ToolDenied",
    "ToolResult",
    "ToolSpec",
    "approval_hash_for",
    "as_quoted_block",
    "canonical_json",
    "validate_arguments",
    "validate_schema",
]
