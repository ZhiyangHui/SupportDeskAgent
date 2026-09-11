import json
from uuid import UUID

from fastapi.testclient import TestClient

from app.agent.factory import ModelConfigurationError
from app.main import app

client = TestClient(app)


def test_health_check_does_not_call_model() -> None:
    """健康检查必须在模型未配置或供应商不可用时仍能正常响应。"""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    # 服务端生成标准 UUID，调用方可以用它关联响应和结构化日志。
    UUID(response.headers["x-request-id"])


def test_request_id_from_trusted_header_is_returned() -> None:
    """合法的上游请求 ID 应贯穿请求，便于跨服务追踪同一条调用链。"""

    response = client.get("/health", headers={"X-Request-ID": "gateway-request-001"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "gateway-request-001"


def test_invalid_request_id_is_replaced() -> None:
    """包含换行或超长内容的请求 ID 不能直接进入响应头和日志。"""

    response = client.get("/health", headers={"X-Request-ID": "request id with spaces"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "request id with spaces"
    UUID(response.headers["x-request-id"])


def test_validation_error_log_contains_field_location(capsys) -> None:
    """422 日志应指出失败字段，但不得记录客户实际提交的敏感内容。"""

    response = client.post(
        "/api/v1/tickets",
        json={
            "title": "测试工单",
            "description": "测试校验日志",
            "customer_email": "private-invalid-email",
        },
    )

    assert response.status_code == 422
    log_records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    validation_log = next(
        record for record in log_records if record["event"] == "request_validation_failed"
    )
    assert validation_log["validation_errors"][0]["location"] == "body.customer_email"
    assert "private-invalid-email" not in json.dumps(validation_log)


def test_chat_returns_service_unavailable_when_model_is_not_configured(monkeypatch) -> None:
    """模型配置缺失应返回明确的 503，不能退化成伪造回复。"""

    async def raise_configuration_error(_service, _content, _conversation_id):
        raise ModelConfigurationError("测试环境未配置模型")

    # Agent 已由 Service 负责调用，因此测试在接口的直接依赖边界替换 chat 方法。
    monkeypatch.setattr(
        "app.api.routes.ConversationService.chat",
        raise_configuration_error,
    )

    response = client.post("/api/v1/agent/chat", json={"message": "你好"})

    assert response.status_code == 503
    assert response.json()["detail"] == "测试环境未配置模型"


def test_chat_error_log_contains_matching_request_id(monkeypatch, capsys) -> None:
    """Agent 异常日志必须携带响应中的请求 ID，502 才能被快速反查。"""

    async def raise_execution_error(_service, _content, _conversation_id):
        raise RuntimeError("测试模型调用失败")

    monkeypatch.setattr("app.api.routes.ConversationService.chat", raise_execution_error)

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "你好"},
        headers={"X-Request-ID": "agent-error-001"},
    )

    assert response.status_code == 502
    assert response.headers["x-request-id"] == "agent-error-001"

    log_records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    error_log = next(record for record in log_records if record["event"] == "agent_execution_failed")
    assert error_log["request_id"] == "agent-error-001"
    assert error_log["error_type"] == "RuntimeError"
    assert "exception" in error_log
