from fastapi import APIRouter
from app.api.v1.endpoints import auth, tracks, arc, sessions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(tracks.router)
api_router.include_router(arc.router)
api_router.include_router(sessions.router)
