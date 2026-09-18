from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import initialize
from .routes import assets, consumer_smokes, datasets, episodes, exports, health, sessions
from .services.worker_manager import worker_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    worker_manager.start_monitor()
    try:
        yield
    finally:
        worker_manager.shutdown_monitor()


app = FastAPI(title="RoboData Studio API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(assets.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(episodes.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(consumer_smokes.router, prefix="/api")


@app.get("/")
def root():
    return {"name": "RoboData Studio API", "docs": "/docs"}
