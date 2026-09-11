import logging
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

REQUEST_ID_HEADER = b"x-request-id"

# 请求 ID 会进入响应头和日志字段，只接受适合日志检索的有限字符，避免换行或超长内容污染日志。
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def configure_logging(log_level: str) -> None:
    """配置应用结构化日志，所有业务日志最终输出为单行 JSON。"""

    level = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _resolve_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    """读取可信的上游请求 ID；缺失或格式异常时生成新的 UUID。"""

    for name, value in headers:
        if name.lower() != REQUEST_ID_HEADER:
            continue

        request_id = value.decode("latin-1").strip()
        if REQUEST_ID_PATTERN.fullmatch(request_id):
            return request_id
        break

    return str(uuid4())


class RequestContextMiddleware:
    """为每个 HTTP 请求绑定请求 ID，并记录不包含业务正文的访问日志。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.logger = structlog.get_logger("app.request")

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(scope.get("headers", []))
        method = scope.get("method", "")
        route = scope.get("path", "")
        status_code = 500
        started_at = perf_counter()

        # ContextVar 按异步任务隔离，同一进程并发处理多个请求时不会串联请求 ID。
        clear_contextvars()
        bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # 未被路由处理的异常在中间件边界记录完整堆栈，随后继续交给 FastAPI 的异常机制。
            self.logger.exception(
                "http_request_unhandled",
                method=method,
                route=route,
                error_type="unhandled_exception",
            )
            raise
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            self.logger.info(
                "http_request_completed",
                method=method,
                route=route,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            clear_contextvars()
