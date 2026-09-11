from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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


class TicketCategory(StrEnum):
    """Agent 可选择的工单分类必须与工单中心筛选值保持一致。"""

    GENERAL = "general"
    ACCOUNT = "account"
    BILLING = "billing"
    TECHNICAL = "technical"
    COMPLAINT = "complaint"


class AgentDecision(BaseModel):
    """模型必须返回的结构化判断，其中建单字段会驱动 LangGraph 的副作用分支。"""

    intent: SupportIntent = Field(description="用户问题所属的客服意图")
    priority: TicketPriority = Field(description="问题的处理优先级")
    requires_human: bool = Field(description="是否必须转交人工客服")
    should_create_ticket: bool = Field(
        description="用户是否明确要求创建工单，且当前信息是否足以形成工单"
    )
    needs_ticket_details: bool = Field(
        description="用户已明确要求建单，但仍缺少具体问题描述，是否需要继续收集信息"
    )
    ticket_title: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
        description="需要建单时提炼的简短工单标题，否则为 null",
    )
    ticket_description: str | None = Field(
        default=None,
        min_length=2,
        max_length=10000,
        description="需要建单时整理的问题现象与客户诉求，否则为 null",
    )
    ticket_category: TicketCategory = Field(
        default=TicketCategory.GENERAL,
        description="工单业务分类",
    )
    reason: str = Field(min_length=1, description="做出当前判断的简短理由")
    reply: str = Field(min_length=1, description="面向客户的简洁中文回复草稿")

    @model_validator(mode="after")
    def ensure_ticket_fields(self) -> "AgentDecision":
        """只有标题和描述都完整时才允许 Graph 进入真实建单分支。"""

        if self.should_create_ticket and self.needs_ticket_details:
            raise ValueError("建单就绪和等待补充不能同时为 true")
        if self.should_create_ticket and not (self.ticket_title and self.ticket_description):
            raise ValueError("创建工单时必须同时提供 ticket_title 和 ticket_description")
        return self
