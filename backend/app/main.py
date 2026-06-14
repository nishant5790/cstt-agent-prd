"""FastAPI application entry point for CSTT Agent Studio.

Phase 1: app wiring + health check. Routers for build/plan/generate are added
in later phases.
"""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import settings
from app.core.logging import get_logger
from app.api import knowledge, planning, generate, auth, sessions

log = get_logger("main")
cfg = settings()

app = FastAPI(
    title="CSTT Agent Studio API",
    description="API for CSTT Agent Studio, a multi-agent system that ingests mixed sources (video, audio, text, docx, xlsx, md, Jira, SharePoint), normalises them into a Canonical Knowledge Model (CKM), and authors grounded training decks through a clarify/refine loop.",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Workspace-Id"],
)


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok",
    " version": __version__,
    "env": cfg.app_env,
    }
    
@app.get("/")
def root() -> dict:
    return {"service": "cstt-agent-studio", "docs": "/docs", "health": "/health"}

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(knowledge.router)
app.include_router(planning.router)
app.include_router(generate.router)
