"""
MCP Client Aggregator
Connects to multiple MCP servers and aggregates their tools
"""
from typing import Dict, List, Any, Optional
import asyncio
import logging
import subprocess
import sys
import json
import base64
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    logger.warning("MCP SDK not installed. Install with: pip install mcp")
    MCP_AVAILABLE = False
    # Create dummy classes for type hints
    class ClientSession:
        pass
    class StdioServerParameters:
        pass


class MCPAggregator:
    """Aggregates tools from multiple MCP servers"""
    
    def __init__(self):
        self.servers: Dict[str, Any] = {}  # Dict[str, dict with server params]
        self.tools: Dict[str, Dict[str, Any]] = {}  # Dict[str, tool metadata]
        self._initialized = False
        
    async def initialize(self):
        """Initialize MCP connections"""
        if self._initialized:
            return
        
        if not MCP_AVAILABLE:
            logger.warning("MCP SDK not available. MCP Aggregator will not function.")
            return
            
        logger.info("Initializing MCP Aggregator...")
        
        # Connect to MCP servers based on configuration
        from core.config import settings
        
        # Optional: LinkedOmics MCP server (stdio)
        if settings.MCP_LINKEDOMICS_SERVER_ENABLED:
            backend_dir = Path(__file__).parent.parent
            server_path = backend_dir / "mcp_servers" / "linkedomics_server.py"

            if not server_path.exists():
                logger.error(f"MCP LinkedOmics Server not found at: {server_path}")
                raise FileNotFoundError(f"MCP LinkedOmics Server not found: {server_path}")

            await self.connect_server(
                "linkedomics",
                str(sys.executable),
                [str(server_path)],
            )
        
        # Literature MCP server (PubMed via NCBI E-utilities)
        if settings.MCP_LITERATURE_SERVER_ENABLED:
            backend_dir = Path(__file__).parent.parent
            server_path = backend_dir / "mcp_servers" / "literature_server.py"
            if not server_path.exists():
                logger.error(f"Literature MCP server not found at: {server_path}")
            else:
                await self.connect_server(
                    "literature",
                    str(sys.executable),
                    [str(server_path)],
                )

        # Phase 3: Add Files and Compute servers here
        
        self._initialized = True
        logger.info(f"MCP Aggregator initialized with {len(self.tools)} tools from {len(self.servers)} servers")
    
    async def connect_server(
        self,
        name: str,
        command: str,
        args: List[str] = None
    ):
        """Connect to an MCP server and discover tools
        
        For Phase 1: We discover tools on connection, but create connections on-demand for tool calls.
        This is simpler and avoids context manager scoping issues.
        
        Args:
            name: Server identifier
            command: Command to run the server
            args: Command arguments
        """
        if not MCP_AVAILABLE:
            logger.warning(f"Cannot connect to MCP server {name}: MCP SDK not available")
            return
        
        logger.info(f"Discovering tools from MCP server: {name} (command: {command} {' '.join(args or [])})")
        
        try:
            server_params = StdioServerParameters(
                command=command,
                args=args or []
            )
            
            # Discover tools by creating a temporary connection
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # Discover tools
                    tools_response = await session.list_tools()
                    tool_count = 0
                    for tool in tools_response.tools:
                        tool_id = f"{name}::{tool.name}"
                        self.tools[tool_id] = {
                            "server": name,
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema
                        }
                        tool_count += 1
                    
                    # Store server parameters for on-demand connections
                    self.servers[name] = {
                        "params": server_params,
                        "command": command,
                        "args": args or [],
                        "connected": True  # Tools discovered, ready for use
                    }
                    
                    logger.info(f"Discovered {tool_count} tools from MCP server: {name}")
                    
        except Exception as e:
            logger.error(f"Failed to discover tools from MCP server {name}: {e}")
            raise
    
    async def call_tool(
        self,
        tool_id: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """Call a tool on an MCP server
        
        For Phase 1: Creates connection on-demand for each tool call.
        This is simpler and avoids context manager scoping issues.
        
        Args:
            tool_id: Tool identifier in format "server::tool_name"
            arguments: Tool arguments
            
        Returns:
            Tool execution result
        """
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not available. Cannot call tools.")
        
        if "::" not in tool_id:
            raise ValueError(f"Invalid tool_id format: {tool_id}. Expected 'server::tool_name'")
        
        server_name, tool_name = tool_id.split("::", 1)
        
        if server_name not in self.servers:
            raise ValueError(f"Server {server_name} not discovered. Available servers: {list(self.servers.keys())}")
        
        server_info = self.servers.get(server_name)
        if not server_info or not server_info.get("connected"):
            raise ValueError(f"Server {server_name} is not ready")
        
        # Create connection on-demand for this tool call
        server_params = server_info["params"]
        logger.debug(f"Creating on-demand connection to {server_name} for tool {tool_name}")
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # Call the tool
                    result = await session.call_tool(tool_name, arguments)
                    
                    # Extract text content from result
                    if hasattr(result, 'content') and result.content:
                        # MCP returns content objects (text/image/etc)
                        text_parts: List[str] = []
                        non_text_parts: List[Dict[str, Any]] = []

                        for content in result.content:
                            # TextContent
                            if hasattr(content, "text"):
                                text_parts.append(content.text)
                                continue
                            if isinstance(content, str):
                                text_parts.append(content)
                                continue

                            # ImageContent (e.g., from FastMCP Image tool outputs)
                            ctype = getattr(content, "type", None)
                            if ctype == "image" and hasattr(content, "data"):
                                raw_data = getattr(content, "data")
                                # Ensure JSON-serializable base64 string
                                if isinstance(raw_data, (bytes, bytearray)):
                                    encoded = base64.b64encode(raw_data).decode("ascii")
                                else:
                                    encoded = raw_data

                                non_text_parts.append(
                                    {
                                        "type": "image",
                                        "data": encoded,
                                        "mimeType": getattr(content, "mimeType", None)
                                        or getattr(content, "mime_type", None)
                                        or "image/png",
                                    }
                                )
                                continue

                            # Fallback: preserve repr for unknown content types
                            non_text_parts.append({"type": "unknown", "repr": repr(content)})

                        # Backwards compatible: if everything is text, return string
                        if non_text_parts == []:
                            return "\n".join(text_parts) if text_parts else str(result)

                        # Otherwise return a structured payload (stringified JSON)
                        payload = {
                            "mcp": {
                                "tool_id": tool_id,
                                "server": server_name,
                                "tool": tool_name,
                            },
                            "text": "\n".join(text_parts) if text_parts else "",
                            "parts": non_text_parts,
                        }
                        return json.dumps(payload)
                    else:
                        return result
                    
        except Exception as e:
            logger.error(f"Error calling tool {tool_id}: {e}", exc_info=True)
            raise
    
    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """List all available tools from all servers
        
        Returns:
            Dictionary mapping tool_id to tool metadata
        """
        return self.tools.copy()
    
    def get_tool_info(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific tool
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            Tool metadata or None if not found
        """
        return self.tools.get(tool_id)
    
    async def cleanup(self):
        """Cleanup MCP connections"""
        logger.info("Cleaning up MCP Aggregator...")
        # Phase 1: On-demand connections don't need cleanup
        # (connections are created per tool call and closed automatically)
        self.servers.clear()
        self.tools.clear()
        self._initialized = False
