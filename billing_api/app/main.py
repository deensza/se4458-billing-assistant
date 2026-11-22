import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .errors import error_body, register_error_handlers
from .routers import v1

logger = logging.getLogger("billing_api")

DESCRIPTION = """
Billing REST API for the **Mobile Provider Billing Assistant** (SE 4458 Midterm, Group 2).

* All operations are versioned under `/api/v1`.
* In deployment every call goes through the API Gateway (Kong).
* Protected operations need `Authorization: Bearer <JWT>`. Get a token from `POST /api/v1/auth/token`.
* Errors always use the format `{"error": {"code": "...", "message": "...", "details": ...}}`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.init_db_on_startup:
        from .database import SessionLocal, engine
        from .models import Base
        from .seed import seed_demo_data

        Base.metadata.create_all(engine)
        if settings.seed_demo_data:
            with SessionLocal() as db:
                seed_demo_data(db)
    yield


app = FastAPI(
    title="Mobile Provider Billing API",
    version="1.0.0",
    description=DESCRIPTION,
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url=None,
)
register_error_handlers(app)
app.include_router(v1.router)


@app.middleware("http")
async def require_api_gateway(request: Request, call_next):
    """Reject requests that did not come through the API Gateway (origin protection)."""
    expected = settings.gateway_shared_secret
    if expected and request.url.path != "/health":
        supplied = request.headers.get("x-gateway-secret", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return JSONResponse(
                status_code=403,
                content=error_body("GATEWAY_REQUIRED", "This API is only reachable through the API Gateway."),
            )
    return await call_next(request)


@app.get("/health", tags=["Health"], summary="Liveness check")
def health():
    return {"status": "ok"}
