"""统一错误分类；业务结果由请求回执决定，异常类型只决定解释方式。"""

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_current_request_id
from app.schema.agent_error import AgentErrorDetail, AgentRequestError


class ModelOutputError(RuntimeError):
    """模型输出未满足协议，纠正后仍无效时停止执行工具。"""


def classify_agent_error(error: Exception) -> AgentRequestError:
    """仅用异常类型分类，不解析可能包含客户信息的异常字符串。"""

    # 延迟导入避免模型工厂、Graph 与错误分类之间形成模块加载循环。
    from app.agent.factory import ModelConfigurationError

    code, message, status = "agent_failed", "本次请求未能完成，请稍后再试。", 502
    if isinstance(error, (TimeoutError, APITimeoutError)):
        code, message, status = "agent_timeout", "客服服务响应超时。", 504
    elif isinstance(error, RateLimitError):
        code, message, status = "model_busy", "客服服务繁忙，请稍后再试。", 503
    elif isinstance(error, (AuthenticationError, ModelConfigurationError)):
        code, message, status = (
            "model_configuration",
            "客服服务配置异常，请联系企业客服。",
            503,
        )
    elif isinstance(error, APIConnectionError):
        code, message, status = "model_unavailable", "暂时无法连接客服模型服务。", 503
    elif isinstance(error, SQLAlchemyError):
        code, message, status = "database_unavailable", "暂时无法访问业务数据。", 503
    elif isinstance(error, (ModelOutputError, ValidationError)):
        code, message = (
            "model_output_invalid",
            "客服模型返回的数据格式不符合要求，本次处理未能完成，请稍后重试。",
        )
    return AgentRequestError(
        AgentErrorDetail(
            code=code, message=message, request_id=get_current_request_id()
        ),
        status,
    )
