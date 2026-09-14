"""双账号基础安全测试；真实账号、注销与跨企业越权由集成测试覆盖。"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.passwords import hash_password, verify_password
from app.db.conversation_repository import ConversationNotFoundError
from app.db.models import Company, Conversation
from app.main import create_app
from app.schema.access import CompanyRegisterRequest, LoginRequest, RegisterRequest
from app.services.conversation_service import ConversationService


@pytest.mark.parametrize("password", ["12345678", "a" * 20, " " * 8, "🙂" * 8])
def test_registration_accepts_length_only(password):
    """客户和企业注册统一只校验长度，纯数字、单类字符和 Unicode 都允许。"""
    fields = {"username": "account", "display_name": "测试", "password": password}
    assert RegisterRequest(**fields).password == password
    assert (
        CompanyRegisterRequest(
            **fields, company_code="company", company_name="测试企业"
        ).password
        == password
    )


@pytest.mark.parametrize("password", ["a" * 7, "a" * 21])
def test_registration_rejects_outside_length(password):
    for schema, extra in (
        (RegisterRequest, {}),
        (
            CompanyRegisterRequest,
            {"company_code": "company", "company_name": "测试企业"},
        ),
    ):
        with pytest.raises(ValidationError):
            schema(username="account", display_name="测试", password=password, **extra)


def test_login_preserves_existing_password_compatibility():
    assert LoginRequest(username="account", password="a" * 30).password == "a" * 30


def test_anonymous_and_legacy_cookies_cannot_access_private_routes():
    with TestClient(create_app()) as client:
        client.cookies.set("supportdesk_customer", "a" * 64)
        client.cookies.set("supportdesk_staff", "9999999999.old-signature")
        for path in (
            "/api/v1/tickets",
            "/api/v1/agent-runs",
            "/api/v1/staff/customers",
            "/api/v1/customer/companies",
        ):
            assert client.get(path).status_code == 401
        assert client.post("/api/v1/tickets", json={}).status_code == 401


def test_password_salts_and_verification():
    first = hash_password("a-test-password-123")
    second = hash_password("a-test-password-123")
    assert first != second
    assert verify_password("a-test-password-123", first)
    assert not verify_password("wrong-password", first)
    assert not verify_password("a-test-password-123", "invalid")


def test_cross_origin_is_rejected_before_database():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/access/customer/login",
            headers={"origin": "https://untrusted.example"},
            json={"username": "demo", "password": "example-password"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_rejects_other_customer_or_company_before_writes():
    company_id, customer_id = uuid4(), uuid4()
    session = AsyncMock()
    session.get.return_value = Company(id=company_id, active=True)
    service = ConversationService(session)
    conversation = Conversation(
        id=uuid4(), company_id=company_id, customer_id=customer_id
    )
    service.repository.get_conversation = AsyncMock(return_value=conversation)
    service.repository.add_message = AsyncMock()
    for customer, company in ((uuid4(), company_id), (customer_id, uuid4())):
        with pytest.raises(ConversationNotFoundError):
            await service.chat(
                "越权消息", conversation.id, customer_id=customer, company_id=company
            )
    service.repository.add_message.assert_not_awaited()
