"""Tool foundation for 3.4: specs, strict schemas, approvals and one broker."""

from __future__ import annotations

from .approvals import APPROVALS_SCHEMA, ApprovalError, ApprovalStore
from .broker import (DEFAULT_MAX_RESULT_CHARS, DEFAULT_TOKEN_TTL, PROVIDER_KINDS,
                     ToolBroker, ToolCall, ToolContext, ToolDenied, ToolResult,
                     ToolSpec, approval_hash_for, as_quoted_block)
from .schema import SchemaError, canonical_json, validate_arguments, validate_schema
from .mcp import (MCPClient, ManifestTool, ToolManifest)
from .mcp_registry import (KINDS, LOCAL_RIGHTS_NOTE, MCP_SERVERS_FILE,
                           MCP_SERVERS_SCHEMA, MCPApprovalError, MCPConfigError,
                           MCPError, MCPNotFound, MCPNotRunning, MCPProtocolError,
                           MCPRegistryError, MCPTimeout, MCPUnavailable,
                           REMOTE_HOST_NOTE, STATUSES, ServerConfig, ServerRegistry,
                           UNTRUSTED_NOTE)

__all__ = [
    "APPROVALS_SCHEMA",
    "ApprovalError",
    "ApprovalStore",
    "DEFAULT_MAX_RESULT_CHARS",
    "DEFAULT_TOKEN_TTL",
    "KINDS",
    "LOCAL_RIGHTS_NOTE",
    "MCP_SERVERS_FILE",
    "MCP_SERVERS_SCHEMA",
    "MCPApprovalError",
    "MCPClient",
    "MCPConfigError",
    "MCPError",
    "MCPNotFound",
    "MCPNotRunning",
    "MCPProtocolError",
    "MCPRegistryError",
    "MCPTimeout",
    "MCPUnavailable",
    "ManifestTool",
    "PROVIDER_KINDS",
    "REMOTE_HOST_NOTE",
    "STATUSES",
    "SchemaError",
    "ServerConfig",
    "ServerRegistry",
    "ToolManifest",
    "UNTRUSTED_NOTE",
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
