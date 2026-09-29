"""将员工整理的已解决工单经验转为审核草稿，不自动公开工单正文或内部备注。"""
import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.identity_models import CustomerAccount
from app.db.knowledge_models import KnowledgeDocument
from app.db.models import Ticket, TicketStatus
from app.schema.knowledge import (
    ExperienceTicketOption,
    ExperienceTicketSource,
    TicketExperienceCreate,
)
from app.services.knowledge_service import KnowledgeConflictError


def redact_experience(text: str, identifiers: list[str]) -> str:
    """规则脱敏只是一道辅助检查，姓名、地址等开放文本仍须员工逐项审核。"""
    for value in sorted(set(identifiers), key=len, reverse=True):
        if value:
            text = text.replace(value, "[已脱敏]")
    for pattern in (
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)",
        r"(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])(?:TK|MO)-[A-Za-z0-9-]+",
        r"(?<![A-Za-z0-9])[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}(?![A-Za-z0-9])",
    ):
        text = re.sub(pattern, "[已脱敏]", text)
    return text


async def ticket_identifiers(session: AsyncSession, ticket: Ticket) -> list[str]:
    customer = await session.get(CustomerAccount, ticket.customer_id) if ticket.customer_id else None
    return [value for value in (ticket.customer_name, ticket.customer_email, ticket.code,
        customer.display_name if customer else None, customer.username if customer else None,
        str(ticket.customer_id) if ticket.customer_id else None,
        ticket.order.code if ticket.order else None) if value]


async def list_experience_tickets(session: AsyncSession, company_id: UUID, keyword: str, offset: int) -> list[ExperienceTicketOption]:
    """候选直接取自数据库，分页有界且在 SQL 层限定企业和完结状态。"""
    query = select(Ticket).where(Ticket.company_id == company_id,
        Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]))
    if keyword:
        query = query.where(or_(Ticket.code.contains(keyword, autoescape=True), Ticket.title.contains(keyword, autoescape=True)))
    tickets = await session.scalars(query.order_by(Ticket.updated_at.desc(), Ticket.id).offset(offset).limit(20))
    results = []
    for ticket in tickets:
        identifiers = await ticket_identifiers(session, ticket)
        results.append(ExperienceTicketOption(code=ticket.code,
            title=redact_experience(ticket.title, identifiers), status=ticket.status.value))
    return results


async def experience_ticket_source(session: AsyncSession, company_id: UUID, code: str) -> ExperienceTicketSource:
    ticket = await session.scalar(select(Ticket).where(Ticket.company_id == company_id, Ticket.code == code))
    if ticket is None:
        raise LookupError("工单不存在")
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise KnowledgeConflictError("请先选择已解决或已关闭的工单。")
    identifiers = await ticket_identifiers(session, ticket)
    return ExperienceTicketSource(code=ticket.code, title=redact_experience(ticket.title, identifiers),
        status=ticket.status.value, description=redact_experience(ticket.description, identifiers),
        desired_resolution=redact_experience(ticket.desired_resolution, identifiers),
        impact_note=redact_experience(ticket.impact_note, identifiers))


async def create_experience(session: AsyncSession, company_id: UUID, data: TicketExperienceCreate) -> KnowledgeDocument:
    # 行锁串行化同一工单的草稿创建；数据库唯一约束同时防止未来入口重复沉淀。
    ticket = await session.scalar(select(Ticket).where(Ticket.company_id == company_id,
        Ticket.code == data.ticket_code).with_for_update())
    if ticket is None:
        raise LookupError("工单不存在")
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise KnowledgeConflictError("仅已解决或已关闭的工单可以整理为经验案例；关闭工单仍需核实实际处理结果。")
    if await session.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.source_ticket_id == ticket.id)):
        raise KnowledgeConflictError("该工单已有经验文档，请在知识库中查看和调整，勿重复创建。")
    identifiers = await ticket_identifiers(session, ticket)
    title = redact_experience(data.title, identifiers)
    # 每个章节都显式标记案例性质；检索只命中单个章节时也不会被误当成统一政策。
    content = "# 历史案例（仅供参考，不构成统一政策或处理承诺）\n\n" + "\n\n".join(
        f"## {label}\n{redact_experience(value, identifiers)}" for label, value in (
            ("问题现象", data.symptom), ("已核实原因（未知可注明未确认）", data.cause),
            ("实际解决办法", data.solution), ("适用范围与限制", data.applicability)))
    row = KnowledgeDocument(company_id=company_id, title=title, content=content,
        source_kind="ticket_case", source_ticket_id=ticket.id)
    session.add(row)
    await session.commit()
    return row


async def validate_case_privacy(session: AsyncSession, row: KnowledgeDocument) -> None:
    """发布前再次检查所有待发布文本，防止编辑分块后重新带入常见敏感信息。"""
    ticket = await session.scalar(select(Ticket).where(Ticket.id == row.source_ticket_id,
        Ticket.company_id == row.company_id))
    if ticket is None:
        raise KnowledgeConflictError("案例关联工单不可用，不能发布。")
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise KnowledgeConflictError("来源工单当前不是已解决或已关闭状态，请核实处理结果后再发布案例。")
    identifiers = await ticket_identifiers(session, ticket)
    texts = [row.title, *[value for chunk in row.draft_chunks for value in (chunk["heading_path"], chunk["content"])]]
    if any(redact_experience(text, identifiers) != text for text in texts):
        raise KnowledgeConflictError("待发布案例仍含可识别信息，请删除姓名、联系方式、订单或工单标识后重新审核。")
