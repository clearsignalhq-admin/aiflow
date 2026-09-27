"""AWS Lambda entry point via Mangum ASGI adapter."""
from mangum import Mangum
from app.main import app


class _StripStagePrefixMiddleware:
    """Strip API Gateway HTTP API stage prefix from path before FastAPI routing.

    HTTP API Gateway v2 includes the stage name in rawPath, e.g. /Prod/api/health.
    FastAPI only knows /api/health, so we strip /Prod before routing.
    """
    def __init__(self, asgi_app, stage: str):
        self._app = asgi_app
        self._prefix = f"/{stage}"

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path: str = scope.get("path", "")
            if path.startswith(self._prefix):
                scope = {**scope, "path": path[len(self._prefix):] or "/"}
        await self._app(scope, receive, send)


handler = Mangum(_StripStagePrefixMiddleware(app, "Prod"), lifespan="off")
