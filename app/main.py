"""FastAPI 入口：提供静态页面与 /api/simulate 推演接口。"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from .engine import SimError, simulate
from .models import SimRequest, normalize

app = FastAPI(title="雨水调蓄池推演", version="1.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": _format(exc)})


def _format(exc) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"] if x not in ("body",))
        msg = err["msg"]
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "输入格式有误：" + "；".join(parts[:5])


@app.post("/api/simulate")
async def run_simulate(request: Request):
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400,
                            content={"detail": "请求体不是合法的 JSON"})
    if not isinstance(raw, dict):
        return JSONResponse(status_code=400,
                            content={"detail": "请求体必须为 JSON 对象"})
    try:
        req = SimRequest.model_validate(raw)
        cfg = normalize(req)
        result = simulate(cfg)
    except (SimError, ValidationError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            return JSONResponse(
                status_code=400,
                content={"detail": "输入格式有误：" + "; ".join(
                    f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                    for e in exc.errors()[:5])})
        # 计算失败：仅返回错误，不保留任何结果（结果在每次请求内构造）
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
