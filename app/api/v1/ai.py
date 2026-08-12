"""IRIS AI proxy — lets Cargo360 run already-formatted prompts via the IRIS gateway.

POST /api/v1/ai/run-prompt   admin: forward a formatted prompt to IRIS, return result.
GET  /api/v1/ai/status       admin: non-secret config snapshot (is IRIS AI wired?).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from app.api.v1.auth import get_current_admin
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai")
router = APIRouter()


class RunPromptBody(BaseModel):
    content: str                       # the already-formatted user content (required)
    system: Optional[str] = None       # optional system instructions
    response_format: str = "text"      # 'text' | 'json'
    model_hint: Optional[str] = None   # e.g. 'claude-haiku-4-5-20251001'; ignored if not claude-*
    temperature: float = 0.0
    max_tokens: int = 2000
    task: Optional[str] = None         # free label for tracing/audit


@router.get("/ai/status")
def ai_status(_admin=Depends(get_current_admin)):
    """Is the IRIS AI channel configured? (no secrets returned)"""
    return iris_ai.status()


@router.post("/ai/run-prompt")
def ai_run_prompt(body: RunPromptBody, admin=Depends(get_current_admin)) -> dict[str, Any]:
    """Forward a formatted prompt to IRIS and return the normalized result."""
    if not (body.content or "").strip():
        raise HTTPException(400, "content is required")
    if body.response_format not in ("text", "json"):
        raise HTTPException(400, "response_format must be 'text' or 'json'")
    if not (0.0 <= body.temperature <= 1.0):
        raise HTTPException(400, "temperature must be between 0.0 and 1.0")
    if not (1 <= body.max_tokens <= 8000):
        raise HTTPException(400, "max_tokens must be between 1 and 8000")

    res = iris_ai.run_prompt(
        body.system or "", body.content,
        response_format=body.response_format,
        model_hint=body.model_hint,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        task=body.task,
    )
    reviewer = admin.get("username") or admin.get("email") or "admin"
    logger.info("ai/run-prompt by=%s task=%s ok=%s", reviewer, body.task, res.get("ok"))
    if not res.get("ok"):
        # Surface a clean 502 for upstream/config errors, keep the structured error.
        err = res.get("error") or {"code": "UNKNOWN", "message": "IRIS AI call failed"}
        raise HTTPException(502, detail=err)
    return res
