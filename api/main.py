"""Thin API seam: ONE endpoint `POST /api/generate` + a static dev-shell.

The interfaces are fixed elsewhere; this seam ONLY serves `generate()` and files — no UI, no product
logic. The red lines are unchanged: no auth / payments / rate-limit / user-data-persist; the server
binds 127.0.0.1 ONLY; the trace stays in `$DATA_DIR` — only its `request_id` leaves. Every error
carries a uniform `{error, message}` body (in Ukrainian) — NEVER a stacktrace or an internal id.

    uv run uvicorn api.main:app        # dev (127.0.0.1:8000)

Decisions: abstain = 200 (a valid outcome); 422 validation / 200+degraded honest-R-10 /
503 generation_unavailable (DeepSeek down — no LLM ⇒ no dovidka) / 504 timeout; the reranker pin
is verified at STARTUP (drift → SystemExit before bind; a load failure is honest-R-10 → serve
degraded); trace_ref = request_id only; timeout 120s (honest worst path: regen×2 ≈ 3 LLM calls
+ reranker)."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

GENERATE_TIMEOUT_S = 120                 # honest worst path, NOT 60 (60 would kill the gate
#                                          mid-retry — regen×2 = 3 LLM calls + reranker + overhead)
QUESTION_MAX = 2000                      # a pasted wall of text must not fly into the LLM budget
STATIC_DIR = Path(__file__).resolve().parents[1] / "spa" / "dev-shell"


class GenerateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    as_of: str | None = None

    @field_validator("question")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question is blank")
        return v.strip()

    @field_validator("as_of")
    @classmethod
    def _iso_date(cls, v):
        if v is None:
            return v
        from datetime import date
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date (YYYY-MM-DD)") from exc
        return v


def _err(status: int, code: str, message: str) -> JSONResponse:
    """Uniform error body: {error: <machine code>, message: <human Ukrainian>}, no stacktrace."""
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _default_generate(question: str, as_of):
    from pipelines.db import connect
    from pipelines.rag.generate import generate
    with connect() as conn:
        return generate(conn, question, as_of=as_of)


def _default_verify_pin():
    from ml.reranker import check_pin
    return check_pin()


def create_app(generate_fn=None, verify_pin=None) -> FastAPI:
    """App factory — generate_fn / verify_pin are injectable so the pins run on a STUB backend (no live
    DeepSeek, no GPU reranker load) via TestClient. Defaults wire the real pipeline."""
    _generate = generate_fn or _default_generate
    _verify_pin = verify_pin or _default_verify_pin

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # "drift is not degradation": verify the reranker pin at STARTUP. A model DRIFT
        # (SystemExit) must refuse to start — before bind — NOT 500 per request. A LOAD failure
        # (RerankerUnavailable) is honest-R-10, not a drift: the server starts and degrades at runtime.
        from ml.reranker import RerankerUnavailable
        try:
            _verify_pin()
        except RerankerUnavailable as exc:
            print(f"[api] reranker unavailable at startup — honest-R-10, serving degraded ({exc}).")
        except SystemExit as exc:
            # A model DRIFT (check_pin → SystemExit): refuse to start. Re-raise as a startup failure so
            # uvicorn logs it and exits WITHOUT binding (the requirement). A bare SystemExit through an
            # async lifespan is mishandled by asyncio (→ CancelledError); RuntimeError is the clean ASGI
            # "startup failed" signal — still no bind, still an honest refusal.
            raise RuntimeError(f"reranker pin drift — refusing to start: {exc}") from exc
        yield

    app = FastAPI(title="Statute RAG API", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        # Uniform 422 body too (not FastAPI's default `detail` array — do not leak internals).
        return _err(422, "validation_error",
                    f"Некоректний запит: питання 1–{QUESTION_MAX} символів, as_of — ISO-дата (YYYY-MM-DD).")

    @app.post("/api/generate")
    async def generate_endpoint(req: GenerateRequest):
        import openai
        from pipelines.rag.generate import render_dovidka, write_trace
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_generate, req.question, req.as_of), GENERATE_TIMEOUT_S)
            html = render_dovidka(result)
        except asyncio.TimeoutError:
            return _err(504, "timeout", f"Перевищено час генерації ({GENERATE_TIMEOUT_S}с).")
        except openai.OpenAIError:
            # DeepSeek unreachable/errored → without the LLM there is NO dovidka: a refusal, not a
            # degrade. honest-R-10 (a fallen channel/reranker) is 200+degraded, handled inside.
            return _err(503, "generation_unavailable", "Сервіс генерації тимчасово недоступний.")
        except Exception:                                    # never a stacktrace outward
            return _err(500, "internal_error", "Внутрішня помилка сервера.")
        attempts = result.get("attempts") or []
        # The seam MUST persist a trace — otherwise trace_ref is a DANGLING pointer, and a replay
        # handle with nothing to replay is worse than no field at all. A dev persist for the first
        # live test: a strange dovidka must be re-openable by its request_id. Persistence must NOT
        # 500 the caller — but if it fails we drop trace_ref to null rather than hand back a handle
        # that resolves to nothing. ⚠ the trace records the QUESTION: prod retention + PII policy is
        # a separate decision (see the write_trace docstring).
        trace_ref = attempts[-1].get("request_id") if attempts else None
        try:
            write_trace(result, req.question, subdir="t14")
        except Exception as exc:  # noqa: BLE001
            print(f"[api] trace write failed ({exc}) — dropping trace_ref (no dangling handle).")
            trace_ref = None
        return {
            "dovidka": result.get("dovidka"),
            "html": html,
            "meta": {
                "route": result.get("route"),
                "abstained": bool(result.get("abstained")),
                "degraded": result.get("degraded", []),      # honest-R-10 surfaced
                "reranked": bool(result.get("reranked")),
                "dropped": result.get("dropped", {}),
                "lint": result.get("lint", {}),
                "duration_ms": int((time.monotonic() - t0) * 1000),   # the dev-shell needs it
            },
            "trace_ref": trace_ref,     # request_id ONLY — and it RESOLVES (traces/t14)
        }

    # Static dev-shell LAST (mount at "/" is a catch-all; the explicit API route is matched first). The
    # real UI is dropped into spa/dev-shell/; this seam only serves the directory.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)          # localhost ONLY (dev)


if __name__ == "__main__":
    main()
