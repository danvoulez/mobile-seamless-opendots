"""Updates for this computer's copy of Open Dots. Linked phones can't reach these."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.update_service import UpdateUnavailable, update_service

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class UpdatePreferences(BaseModel):
    auto: bool


@router.get("/update")
async def update_status():
    return update_service.status()


@router.post("/update/check")
async def check_for_update():
    return await update_service.check()


@router.post("/update")
async def install_update():
    try:
        return await update_service.request()
    except UpdateUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/update")
async def set_update_preferences(preferences: UpdatePreferences):
    return update_service.set_auto(preferences.auto)
