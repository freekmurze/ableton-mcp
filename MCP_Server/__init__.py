"""Legacy REST API server package.

The MCP server, the thing Claude drives, now lives in the ``ableton_mcp``
package under ``src/``. What remains here is ``rest_api_server``, the optional
HTTP interface for Ollama, OpenAI, and other non-MCP clients, kept for its
existing test suite and the people who rely on it.

New code should import from ``ableton_mcp``.
"""
