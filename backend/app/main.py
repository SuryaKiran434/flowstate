from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.db.session import Base, engine

# Import all ORM models so SQLAlchemy registers them with Base.metadata
# before create_all resolves foreign keys across tables.
from app.models import user, track, session, arc_template, collab  # noqa: F401

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Flowstate API",
    description="Emotional arc engine that curates dynamic listening sessions.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
