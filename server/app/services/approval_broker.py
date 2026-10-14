import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.config import settings
from app.services.storage_service import storage_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PendingApproval:
    request_id: str
    future: asyncio.Future
    allows_always: bool = False
    # "permission": allow / always / deny. "question": the assistant asks the
    # person to choose (OpenCode's question tool); answered with "answer" and
    # the chosen labels, or "deny" to leave it unanswered.
    kind: str = "permission"


class ApprovalBroker:
    """In-process approval coordinator for the local single-user server."""

    def __init__(self):
        self.pending: Dict[str, PendingApproval] = {}
        self._answers: Dict[str, List[List[str]]] = {}

    def open(
        self,
        thread_id: str,
        bot_id: str,
        call: Any,
        request_id: Optional[str] = None,
        always: Optional[list] = None,
        kind: str = "permission",
    ) -> Dict[str, Any]:
        request_id = request_id or f"req-{uuid.uuid4().hex[:10]}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        # `always`: what "Always allow" would allow from then on (OpenCode steps).
        self.pending[request_id] = PendingApproval(request_id, future, allows_always=bool(always), kind=kind)

        approval = {
            "request_id": request_id,
            "thread_id": thread_id,
            "bot_id": bot_id,
            "tool": call.name,
            "summary": call.summary,
            "arguments": call.arguments_for_display,
            "status": "pending",
            "created_at": _now(),
        }
        if always:
            approval["always"] = list(always)
        if kind != "permission":
            approval["kind"] = kind
        storage_service.add_approval(approval)
        storage_service.add_audit_event({
            "event": "approval.opened",
            "request_id": request_id,
            "thread_id": thread_id,
            "tool": call.name,
            "created_at": approval["created_at"],
        })
        return approval

    async def wait(self, request_id: str) -> str:
        pending = self.pending.get(request_id)
        if not pending:
            return "expired"

        try:
            return await asyncio.wait_for(
                asyncio.shield(pending.future),
                timeout=settings.APPROVAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            if not pending.future.done():
                pending.future.set_result("expired")
            storage_service.update_approval(request_id, {
                "status": "expired",
                "resolved_at": _now(),
            })
            storage_service.add_audit_event({
                "event": "approval.expired",
                "request_id": request_id,
                "created_at": _now(),
            })
            return "expired"
        finally:
            self.pending.pop(request_id, None)

    def resolve(self, request_id: str, action: str, answers: Optional[List[List[str]]] = None) -> bool:
        pending = self.pending.get(request_id)
        if not pending or pending.future.done():
            return False
        if pending.kind == "question":
            # A question is answered, or left unanswered ("deny"); never allowed.
            if action not in ("answer", "deny") or (action == "answer" and not answers):
                return False
        elif action == "answer":
            return False
        if action == "always" and not pending.allows_always:
            action = "allow"

        update: Dict[str, Any] = {"status": action, "resolved_at": _now()}
        if action == "answer":
            self._answers[request_id] = [list(answer) for answer in answers or []]
            update["answers"] = self._answers[request_id]
        pending.future.set_result(action)
        storage_service.update_approval(request_id, update)
        storage_service.add_audit_event({
            "event": f"approval.{action}",
            "request_id": request_id,
            "created_at": _now(),
        })
        return True


    def take_answers(self, request_id: str) -> Optional[List[List[str]]]:
        """The labels chosen for a question that was answered (once)."""
        return self._answers.pop(request_id, None)


approval_broker = ApprovalBroker()
