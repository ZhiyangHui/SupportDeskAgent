"""客户可见的错误协议，禁止直接透传模型供应商或数据库异常文本。"""

from typing import Literal

from pydantic import BaseModel


class AgentErrorDetail(BaseModel):
    """操作结果独立于 HTTP 状态，避免把回复失败解释成建单失败。"""

    code: str
    message: str
    request_id: str
    retryable: bool = False
    outcome: Literal["not_executed", "ticket_created", "unknown"] = "unknown"
    ticket_code: str | None = None


class AgentRequestError(Exception):
    """携带安全错误供 API 返回，原始错误通过异常链保留在日志中。"""

    def __init__(self, detail: AgentErrorDetail, status_code: int = 502) -> None:
        super().__init__(detail.message)
        self.detail = detail
        self.status_code = status_code
