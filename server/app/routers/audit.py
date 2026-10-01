from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from typing import Any, Dict, Iterable, List

from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

USAGE_FIELDS = ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens")


@router.get("", response_model=List[Dict[str, Any]])
async def get_audit_events(limit: int = Query(100, ge=1, le=500)):
    return storage_service.get_audit_events(limit)


def summarize_model_usage(replies: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Core: model.reply audit events → totals overall and per model, costliest first."""
    def empty() -> Dict[str, Any]:
        return {"replies": 0, **{field: 0 for field in USAGE_FIELDS}, "cost_usd": 0.0, "replies_without_cost": 0}

    total, per_model = empty(), {}
    for reply in replies:
        for bucket in (total, per_model.setdefault(reply.get("model") or "unknown", empty())):
            bucket["replies"] += 1
            for field in USAGE_FIELDS:
                bucket[field] += int(reply.get(field) or 0)
            if isinstance(reply.get("cost_usd"), (int, float)):
                bucket["cost_usd"] += reply["cost_usd"]
            else:
                # Providers other than Vercel AI Gateway don't report a price.
                bucket["replies_without_cost"] += 1
    models = [{"model": model, **bucket} for model, bucket in per_model.items()]
    models.sort(key=lambda item: (-item["cost_usd"], -item["input_tokens"]))
    return {**total, "models": models}


@router.get("/usage")
async def get_model_usage(days: int = Query(30, ge=1, le=366)):
    """What the model calls of the last `days` days used and cost."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {"days": days, **summarize_model_usage(storage_service.get_audit_events_since(since, "model.reply"))}
