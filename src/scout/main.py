"""hisaab-scout HTTP API."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings, get_settings
from .errors import ScoutError
from .events.importer import EventImporter
from .events.models import ErrorResponse, ImportRequest, ImportResponse
from .llm import make_llm
from .security import RateLimiter, caller_id
from .vendors.check import check_vendor
from .vendors.models import VendorCheckRequest, VendorCheckResponse
from .vendors.registry import FixtureRegistry, Registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def build_registry(settings: Settings) -> Registry | None:
    if settings.gst_registry == "fixture":
        path = Path(settings.gst_registry_fixture_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return FixtureRegistry(path)
    return None


def create_app(settings: Settings | None = None, *, importer: EventImporter | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.importer = importer or EventImporter(settings, make_llm(settings))
        app.state.registry = build_registry(settings)
        app.state.limiter = RateLimiter(settings.scout_rate_limit_per_minute)
        yield

    app = FastAPI(
        title="hisaab-scout",
        version=__version__,
        summary="Reads public web pages for Hisaab.",
        description=(
            "Imports an event from a link, and checks the vendor on a bill. Every value read by AI comes "
            "with the words on the page it came from, and code decides what's kept."
        ),
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )

    @app.exception_handler(ScoutError)
    async def scout_error(_: Request, err: ScoutError) -> JSONResponse:
        body = {"code": err.code, "message": err.message}
        if err.upstream_status is not None:
            body["upstream_status"] = err.upstream_status
        return JSONResponse({"error": body}, status_code=err.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, err: RequestValidationError) -> JSONResponse:
        first = err.errors()[0] if err.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": f"{where}: {first.get('msg', 'invalid')}"}},
            status_code=422)

    def guard(request: Request) -> None:
        s: Settings = request.app.state.settings
        request.app.state.limiter.check(caller_id(request, s))

    @app.get("/health", tags=["meta"])
    async def health(request: Request) -> dict:
        s: Settings = request.app.state.settings
        return {
            "ok": True,
            "version": __version__,
            "ai": "mock" if s.ai_mock else ("groq" if s.groq_api_key else "off"),
            "gst_registry": s.gst_registry,
        }

    @app.post(
        "/v1/events/import",
        tags=["events"],
        response_model=ImportResponse,
        dependencies=[Depends(guard)],
        responses={502: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
        summary="Read an event page and return the fields for a new collection",
    )
    async def import_event(body: ImportRequest, request: Request) -> ImportResponse:
        return await request.app.state.importer.import_url(body.url)

    @app.post(
        "/v1/vendors/check",
        tags=["vendors"],
        response_model=VendorCheckResponse,
        dependencies=[Depends(guard)],
        summary="Check the GSTIN printed on a bill",
    )
    def vendor_check(body: VendorCheckRequest, request: Request) -> VendorCheckResponse:
        return check_vendor(body, request.app.state.registry)

    return app


app = create_app()
