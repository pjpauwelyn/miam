from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from routes import auth, onboarding, profile, eat_in, eat_out, sessions, discover, feedback


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


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
    return {"status": "ok", "version": "0.1.0"}
