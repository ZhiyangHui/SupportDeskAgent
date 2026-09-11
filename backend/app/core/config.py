import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 后端配置固定从 backend/.env 读取，与前端公开配置形成明确的安全边界。
# 使用绝对路径后，无论开发者从仓库根目录还是 backend 目录启动，读取结果都保持一致。
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """集中管理后端运行配置，避免业务代码直接读取环境变量。"""

    app_name: str = "SupportDesk Agent API"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://supportdesk:supportdesk_dev@127.0.0.1:5432/supportdesk"

    # 默认值与 .env.example 保持一致，未提供配置文件时也会选择 DeepSeek V4 Flash。
    model_name: str = "deepseek-v4-flash"
    model_api_key: str = Field(default="", repr=False)
    model_base_url: str | None = "https://api.deepseek.com"

    # LangSmith 使用行业标准变量名，因此通过 validation_alias 绕过 SUPPORT_ 前缀读取。
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY", repr=False)
    langsmith_project: str = Field(
        default="supportdesk-agent-dev",
        validation_alias="LANGSMITH_PROJECT",
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias="LANGSMITH_ENDPOINT",
    )
    langsmith_workspace_id: str = Field(default="", validation_alias="LANGSMITH_WORKSPACE_ID")

    # 本地阶段只允许 Vue 开发服务器跨域访问，生产环境应改为实际前端域名。
    # localhost 与 127.0.0.1 在浏览器中属于不同来源，本地开发需要同时显式放行。
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="SUPPORT_",
        extra="ignore",
    )

    def configure_langsmith_environment(self) -> None:
        """把已校验的 LangSmith 配置同步给 LangChain 自动追踪机制。"""

        # LangChain 在创建回调追踪器时读取标准环境变量，这里统一同步可避免各模块重复配置。
        os.environ["LANGSMITH_TRACING"] = str(self.langsmith_tracing).lower()
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = self.langsmith_endpoint

        if self.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key
        if self.langsmith_workspace_id:
            os.environ["LANGSMITH_WORKSPACE_ID"] = self.langsmith_workspace_id


@lru_cache
def get_settings() -> Settings:
    """复用同一个配置实例，避免每次请求都重新解析环境变量和配置文件。"""

    return Settings()
