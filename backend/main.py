import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from routes import auth, onboarding, profile, eat_in, eat_out, sessions, discover, feedback

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting miam backend v%s", "0.1.0")
    from db.connection import init_pool, close_pool
    await init_pool()

    # Create shared HTTP client for Supabase REST calls
    import httpx
    app.state.http_client = httpx.AsyncClient(timeout=30.0)

    yield

    # Shutdown
    await app.state.http_client.aclose()
    await close_pool()
    logger.info("Shutdown complete")


app = FastAPI(
    title="miam API",
    description="Food intelligence backend — Eat In + Eat Out",
    version="0.1.0",
    lifespan=lifespan,
)

# Development default: open. Set ALLOWED_ORIGINS=https://miam-app-umber.vercel.app in production.
_origins = ["*"] if settings.ALLOWED_ORIGINS == "*" else [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(eat_in.router, prefix="/api/eat-in", tags=["eat-in"])
app.include_router(eat_out.router, prefix="/api/eat-out", tags=["eat-out"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(discover.router, prefix="/api/discover", tags=["discover"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])


@app.get("/health")
async def health_check():
    db_ok = False
    try:
        from db.connection import get_pool
        pool = await get_pool()
        if pool and hasattr(pool, "acquire"):
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return {"status": status, "version": "0.1.0", "db": "connected" if db_ok else "disconnected"}
