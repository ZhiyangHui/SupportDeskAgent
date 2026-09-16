import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.access_routes import router as access_router
from app.api.agent_run_routes import router as agent_run_router
from app.api.customer_routes import router as customer_router
from app.api.order_routes import router as order_router
from app.api.routes import router
from app.api.staff_customer_routes import router as staff_customer_router
from app.api.ticket_routes import router as ticket_router
from app.core.access import require_staff
from app.core.config import get_settings
from app.core.logging import RequestContextMiddleware, configure_logging

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用，便于测试时获得相互隔离的应用实例。"""

    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )
    app.include_router(order_router)

    # CORS 仅控制浏览器来源；客户归属和企业权限由独立依赖校验。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 请求上下文中间件在路由外层统一生成请求 ID，使业务日志与 HTTP 响应可以准确关联。
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(RequestValidationError)
    async def log_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """记录 422 的字段位置和原因，但不记录用户输入，避免日志泄露客户数据。"""

        validation_errors = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        logger.warning(
            "request_validation_failed",
            method=request.method,
            route=request.url.path,
            validation_errors=validation_errors,
        )
        # 继续复用 FastAPI 的标准错误响应，避免前端因日志增强而需要修改协议。
        return await request_validation_exception_handler(request, exc)

    app.include_router(router)
    app.include_router(access_router)
    app.include_router(customer_router)
    app.include_router(staff_customer_router)
    app.include_router(ticket_router, dependencies=[Depends(require_staff)])
    app.include_router(agent_run_router, dependencies=[Depends(require_staff)])
    return app


app = create_app()

#uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
