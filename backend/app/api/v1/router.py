from fastapi import APIRouter

from app.api.v1.endpoints import arc, auth, collab, sessions, templates, tracks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(tracks.router)
api_router.include_router(arc.router)
api_router.include_router(sessions.router)
api_router.include_router(templates.router)
api_router.include_router(collab.router)
