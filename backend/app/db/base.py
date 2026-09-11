from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """项目内所有 SQLAlchemy 持久化模型的统一声明式基类。"""