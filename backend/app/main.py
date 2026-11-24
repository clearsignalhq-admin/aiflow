from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import settings
from app.version import __version__
from app.core.limiter import limiter
from app.core.supabase_client import bootstrap_admin
from app.api.routes import router
from app.api.user_routes import router as user_router
from app.api.runs_routes import router as runs_router
from app.api.suites_routes import router as suites_router
from app.api.export_routes import router as export_router
from app.api.cloud_routes import router as cloud_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.admin_email:
        try:
            await bootstrap_admin(settings.admin_email)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("bootstrap_admin failed: %s", exc)
    yield


app = FastAPI(
    title="AiFlow API",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Added before CORS so CORS stays outermost and 413 responses carry CORS headers.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(user_router)
app.include_router(runs_router)
app.include_router(suites_router)
app.include_router(export_router)
app.include_router(cloud_router)
