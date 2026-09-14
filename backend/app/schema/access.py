"""双端账号协议：企业编号与账号角色不得由业务请求自行伪造。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    # 登录保留旧密码的长度兼容性，新密码规则仅在注册时执行。
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(LoginRequest):
    # 两端注册只限制长度，不要求字符种类，也不裁剪用户输入的空格。
    password: str = Field(min_length=8, max_length=20, repr=False)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class StaffLoginRequest(LoginRequest):
    company_code: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9-]+$")


class CompanyRegisterRequest(RegisterRequest):
    company_code: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9-]+$")
    company_name: str = Field(min_length=1, max_length=100)

    @field_validator("company_name")
    @classmethod
    def nonblank_company(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("企业名称不能为空")
        return value.strip()


class Principal(BaseModel):
    """服务端从登录记录解析的可信身份，不能由客户端指定。"""

    id: UUID
    audience: Literal["customer", "staff"]
    display_name: str
    company_id: UUID | None = None
    company_name: str | None = None


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
