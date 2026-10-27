from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Ctx, get_credentials, get_ctx
from app.core.auth import require_token
from app.schemas.common import Ok
from app.schemas.settings import ApiKeyIn, ApiKeyStatus, AppSettings, SettingsPatch
from app.services.settings_service import CredentialStore
from app.ws.events import hub

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
async def get_settings(ctx: Ctx = Depends(get_ctx)) -> AppSettings:
    return ctx.settings


@router.put("", response_model=AppSettings)
async def replace_settings(body: AppSettings, ctx: Ctx = Depends(get_ctx)) -> AppSettings:
    return _changed(ctx.settings_service.replace(body))


@router.patch("", response_model=AppSettings)
async def patch_settings(body: SettingsPatch, ctx: Ctx = Depends(get_ctx)) -> AppSettings:
    return _changed(ctx.settings_service.patch(body))


@router.post("/reset", response_model=AppSettings)
async def reset_settings(ctx: Ctx = Depends(get_ctx)) -> AppSettings:
    return _changed(ctx.settings_service.reset())


def _changed(s: AppSettings) -> AppSettings:
    """Both windows apply appearance / voice settings live (the dot has no settings UI of its own)."""
    hub.publish("settings.changed", {})
    return s


# API key: write-only. Responses never contain the key (PRD §3.3 / §11.1).
@router.get("/api-key", response_model=ApiKeyStatus, dependencies=[Depends(require_token)])
async def api_key_status(creds: CredentialStore = Depends(get_credentials)) -> ApiKeyStatus:
    return ApiKeyStatus(has_api_key=creds.has_api_key(), credential_store=creds.backend)


@router.put("/api-key", response_model=ApiKeyStatus, dependencies=[Depends(require_token)])
async def set_api_key(body: ApiKeyIn, creds: CredentialStore = Depends(get_credentials)) -> ApiKeyStatus:
    creds.set_api_key(body.api_key.strip())
    hub.publish("settings.changed", {})
    return ApiKeyStatus(has_api_key=True, credential_store=creds.backend)


@router.delete("/api-key", response_model=Ok, dependencies=[Depends(require_token)])
async def delete_api_key(creds: CredentialStore = Depends(get_credentials)) -> Ok:
    creds.delete_api_key()
    hub.publish("settings.changed", {})
    return Ok()
