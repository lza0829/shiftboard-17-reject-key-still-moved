from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import handover as svc

router = APIRouter(prefix="/handovers", tags=["交班"])


class StartBody(BaseModel):
    from_shift_id: int = Field(..., description="交班班次")
    to_shift_id: int = Field(..., description="接班班次")


class RejectionItem(BaseModel):
    batch_id: int = Field(..., description="清单内批次 id")
    reason: str = Field(..., description="拒收原因（必填）")


class RejectionsBody(BaseModel):
    rejections: list[RejectionItem] = Field(default_factory=list)


@router.get("")
def get_handovers():
    return svc.list_handovers()


@router.get("/{handover_id}")
def get_one(handover_id: int):
    return svc.get_handover(handover_id)


@router.get("/{handover_id}/rejections")
def get_rejections(handover_id: int):
    return svc.list_rejections(handover_id)


@router.get("/{handover_id}/proof")
def get_proof(handover_id: int):
    """只读：按交班单 id 查询每次完成落下的持久化分桶证明。"""
    return svc.get_proof(handover_id)


@router.put("/{handover_id}/rejections")
def put_rejections(handover_id: int, body: RejectionsBody):
    return svc.set_rejections(handover_id, [r.model_dump() for r in body.rejections])


@router.post("/start")
def start(body: StartBody):
    return svc.start_handover(body.from_shift_id, body.to_shift_id)


@router.post("/{handover_id}/complete")
def complete(handover_id: int):
    return svc.complete_handover(handover_id)
