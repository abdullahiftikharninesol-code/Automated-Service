import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, dashboard, followups, leads, organizations, public
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Simple, tenant-safe lead follow-up for small HVAC businesses.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(leads.router)
app.include_router(organizations.router)
app.include_router(followups.router)
app.include_router(public.router)


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, error: Exception) -> JSONResponse:
    logging.getLogger("missed_lead_rescue").exception("Unhandled application error", exc_info=error)
    detail = str(error) if settings.environment == "development" else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail})
