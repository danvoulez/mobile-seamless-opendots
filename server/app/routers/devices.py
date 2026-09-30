"""Link a phone to this computer so it can continue the same conversations."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
import segno

from app.services.device_service import PairingError, client_address, device_service
from app.services.event_bus import event_bus
from app.services.host_info import base_urls, computer_name, device_noun, reachable_by_devices

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


def _client(request: Request) -> dict:
    return getattr(request.state, "client", None) or {}


def _require_owner(request: Request) -> None:
    if _client(request).get("kind") != "owner":
        raise HTTPException(status_code=403, detail=f"Manage devices from Open Dots on your {device_noun()}.")


@router.post("/pairing")
async def create_pairing(request: Request):
    _require_owner(request)
    pairing = device_service.create_pairing_code()
    addresses = base_urls()
    url = f"{addresses[0]['url']}/m/?pair={pairing['code']}" if addresses else None
    qr = None
    if url:
        matrix = segno.make(url, error="m").matrix
        qr = {"size": len(matrix), "rows": ["".join("1" if cell else "0" for cell in row) for row in matrix]}
    return {
        **pairing,
        "url": url,
        "qr": qr,
        "addresses": addresses,
        "reachable": reachable_by_devices(),
        "computer_name": computer_name(),
    }


@router.post("/pair")
async def pair_device(body: PairRequest, request: Request, response: Response):
    try:
        device, token = device_service.redeem(
            body.code, request.headers.get("user-agent", ""), client_address(request)
        )
    except PairingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    device_service.set_cookie(response, token, secure=request.url.scheme == "https")
    response.headers["Cache-Control"] = "no-store"
    event_bus.publish({"type": "device.linked", "device": device})
    return {"device": device, "computer_name": computer_name()}


@router.get("/current")
async def current_device(request: Request):
    return {"device": _client(request).get("device"), "computer_name": computer_name()}


@router.delete("/current")
async def unlink_current_device(request: Request, response: Response):
    device = _client(request).get("device")
    if not device:
        raise HTTPException(status_code=400, detail="This browser is not a linked device.")
    device_service.revoke(device["id"])
    device_service.clear_cookie(response)
    event_bus.publish({"type": "device.unlinked", "deviceId": device["id"]})
    return {"status": "ok"}


@router.get("")
async def list_devices(request: Request):
    _require_owner(request)
    return device_service.list_devices()


@router.delete("/{device_id}")
async def unlink_device(device_id: str, request: Request):
    _require_owner(request)
    if not device_service.revoke(device_id):
        raise HTTPException(status_code=404, detail="Device not found.")
    event_bus.publish({"type": "device.unlinked", "deviceId": device_id})
    return {"status": "ok", "deleted_id": device_id}
