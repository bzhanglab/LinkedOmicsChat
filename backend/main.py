"""
cpgAgent FastAPI Backend
Main application entry point with API routes and agent orchestration
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from api import chat, agents, datasets, analyses, workflows, auth
from core.config import settings
from core.database import init_db
from services.agent_orchestrator import AgentOrchestrator
from services.websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# WebSocket connection manager
ws_manager = ConnectionManager()

# Agent orchestrator
orchestrator = AgentOrchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup and shutdown events"""
    # Startup
    logger.info("Starting cpgAgent backend...")
    await init_db()
    await orchestrator.initialize()
    
    # Set orchestrator for workflows
    workflows.set_orchestrator(orchestrator)
    
    logger.info("cpgAgent backend started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down cpgAgent backend...")
    await orchestrator.cleanup()
    logger.info("cpgAgent backend shut down successfully")


app = FastAPI(
    title="cpgAgent API",
    description="Modern Agentic Platform for Multi-Omics Analysis",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
logger.info(f"CORS origins configured: {settings.CORS_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to cpgAgent API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "operational"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
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
            
            # Handle different message types
            if data.get("type") == "chat":
                # Process chat message through agent orchestrator
                response = await orchestrator.process_query(
                    query=data.get("message"),
                    user_id=client_id,
                    session_id=data.get("session_id")
                )
                await ws_manager.send_personal_message(response, client_id)
            
            elif data.get("type") == "ping":
                await ws_manager.send_personal_message(
                    {"type": "pong"},
                    client_id
                )
            
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(client_id)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])
app.include_router(datasets.router, prefix="/api/v1/datasets", tags=["Datasets"])
app.include_router(analyses.router, prefix="/api/v1/analyses", tags=["Analyses"])
app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["Workflows"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
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
        reload=settings.DEBUG
    )
