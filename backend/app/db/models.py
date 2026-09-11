from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ConversationStatus(StrEnum):
    """会话状态使用稳定枚举，避免数据库中出现不可控的自由文本。"""

    ACTIVE = "active"
    HANDED_OFF = "handed_off"
    CLOSED = "closed"


class MessageRole(StrEnum):
    """数据库只保存业务会话角色，系统提示词由 Agent 运行时注入。"""

    CUSTOMER = "customer"
    AGENT = "agent"


class TicketStatus(StrEnum):
    """工单生命周期状态；状态跳转是否合法由 Service 层统一判断。"""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriorityValue(StrEnum):
    """数据库中的工单优先级与 Agent 输出值保持一致。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketSource(StrEnum):
    """区分人工创建和会话转单，便于后续统计 Agent 自动化效果。"""

    MANUAL = "manual"
    AGENT = "agent"


class TicketActivityType(StrEnum):
    """工单审计记录类型，不使用自由文本表示关键状态变化。"""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    ASSIGNED = "assigned"
    NOTE_ADDED = "note_added"


class Conversation(Base):
    """一段客户与 Agent 的连续会话。"""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", values_callable=lambda enum: [item.value for item in enum]),
        default=ConversationStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # delete-orphan 确保消息生命周期从属于会话，但生产环境删除会话仍需权限和审计流程。
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    """会话中的一条不可变消息。"""

    __tablename__ = "messages"
    __table_args__ = (
        # 时间相同的消息通过 UUID 再次稳定排序，保证每次构造模型上下文的顺序一致。
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Tool 元数据与客户可见回复分开保存，刷新历史时仍能准确展示真实工具执行记录。
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_payload: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Ticket(Base):
    """客服工单主记录，保存当前状态；完整变化历史由 TicketActivity 维护。"""

    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status_priority_updated", "status", "priority", "updated_at"),
        Index("ix_tickets_conversation_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", values_callable=lambda enum: [item.value for item in enum]),
        default=TicketStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[TicketPriorityValue] = mapped_column(
        Enum(
            TicketPriorityValue,
            name="ticket_priority",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=TicketPriorityValue.MEDIUM,
        nullable=False,
    )
    source: Mapped[TicketSource] = mapped_column(
        Enum(TicketSource, name="ticket_source", values_callable=lambda enum: [item.value for item in enum]),
        default=TicketSource.MANUAL,
        nullable=False,
    )
    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    activities: Mapped[list["TicketActivity"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TicketActivity.created_at, TicketActivity.id",
    )


class TicketActivity(Base):
    """工单操作审计记录；已写入的记录不允许通过普通业务接口修改。"""

    __tablename__ = "ticket_activities"
    __table_args__ = (Index("ix_ticket_activities_ticket_created", "ticket_id", "created_at", "id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_type: Mapped[TicketActivityType] = mapped_column(
        Enum(
            TicketActivityType,
            name="ticket_activity_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    operator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship(back_populates="activities")
