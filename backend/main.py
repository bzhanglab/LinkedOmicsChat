"""
LinkedOmicsChat FastAPI backend.
Main application entry point with API routes and MCP orchestration.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from api import admin, chat, auth, tools
from core.config import settings
from core.database import init_db
from services.mcp_orchestrator import MCPOrchestrator
from services.websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# WebSocket connection manager
ws_manager = ConnectionManager()

# MCP orchestrator (LangGraph-backed)
mcp_orchestrator = MCPOrchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup and shutdown events"""
    logger.info("Starting LinkedOmicsChat backend...")
    await init_db()

    logger.info("Initializing MCP orchestrator...")
    await mcp_orchestrator.initialize()
    logger.info("MCP orchestrator initialized")

    # Wire orchestrator into chat and tools APIs
    import api.chat as chat_module
    import api.tools as tools_module
    chat_module.orchestrator = mcp_orchestrator
    tools_module.orchestrator = mcp_orchestrator

    logger.info("LinkedOmicsChat backend started successfully")
    logger.info(f"Available MCP tools: {list(mcp_orchestrator.mcp_aggregator.list_tools().keys())}")

    yield

    logger.info("Shutting down LinkedOmicsChat backend...")
    await mcp_orchestrator.cleanup()
    logger.info("LinkedOmicsChat backend shut down successfully")


app = FastAPI(
    title="LinkedOmicsChat API",
    description="Natural language interface for cancer multi-omics analysis via LinkedOmics MCP tools",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
# In development, also allow any LAN IP (10.x, 192.168.x, 172.16-31.x) on port 3000/3001
# so the app works when accessed from phones or other devices on the same network.
_cors_origins = list(settings.CORS_ORIGINS) if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS]
_cors_origin_regex = None
if settings.ENVIRONMENT == "development":
    _cors_origin_regex = (
        r"^http://(localhost|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"):(3000|3001|8000)$"
    )
    logger.info("Development mode: CORS allows all LAN IPs on ports 3000/3001/8000")
else:
    logger.info(f"CORS origins configured: {_cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Welcome to LinkedOmicsChat API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "operational"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "api": "up",
            "agents": "up",
            "database": "up"
        }
    }


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time communication"""
    await ws_manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "chat":
                response = await mcp_orchestrator.process_query(
                    query=data.get("message"),
                    user_id=client_id,
                    session_id=data.get("session_id")
                )
                await ws_manager.send_personal_message(response, client_id)

            elif data.get("type") == "ping":
                await ws_manager.send_personal_message({"type": "pong"}, client_id)

    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(client_id)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(tools.router, prefix="/api/v1/tools", tags=["Tools"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        reload_dirs=["api", "core", "models", "services", "mcp_servers"],
    )
