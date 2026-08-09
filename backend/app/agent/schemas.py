from enum import StrEnum

from pydantic import BaseModel, Field


class SupportIntent(StrEnum):
    """第一版支持的客服意图，后续增加意图时需要同步扩展评测集。"""

    GENERAL = "general"
    ACCOUNT = "account"
    ORDER = "order"
    TICKET = "ticket"
    COMPLAINT = "complaint"


class TicketPriority(StrEnum):
    """工单优先级使用稳定的英文值，展示层负责转换为中文。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class AgentDecision(BaseModel):
    """模型必须返回的结构化判断，字段会直接驱动 LangGraph 路由。"""

    intent: SupportIntent = Field(description="用户问题所属的客服意图")
    priority: TicketPriority = Field(description="问题的处理优先级")
    requires_human: bool = Field(description="是否必须转交人工客服")
    reason: str = Field(min_length=1, description="做出当前判断的简短理由")
    reply: str = Field(min_length=1, description="面向客户的简洁中文回复草稿")

