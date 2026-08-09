from fastapi.testclient import TestClient

from app.agent.factory import ModelConfigurationError
from app.main import app

client = TestClient(app)


def test_health_check_does_not_call_model() -> None:
    """健康检查必须在模型未配置或供应商不可用时仍能正常响应。"""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_returns_service_unavailable_when_model_is_not_configured(monkeypatch) -> None:
    """模型配置缺失应返回明确的 503，不能退化成伪造回复。"""

    def raise_configuration_error():
        raise ModelConfigurationError("测试环境未配置模型")

    # 路由模块已直接导入工厂函数，因此在路由边界替换可以精确覆盖当前接口行为。
    monkeypatch.setattr("app.api.routes.get_support_graph", raise_configuration_error)

    response = client.post("/api/v1/agent/chat", json={"message": "你好"})

    assert response.status_code == 503
    assert response.json()["detail"] == "测试环境未配置模型"

