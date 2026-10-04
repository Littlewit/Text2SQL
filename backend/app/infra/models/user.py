"""用户、角色与数据范围模型（§5.1 user/role/user_role/data_scope）。"""


from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, SmallInteger, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.models.base import Base, IntPkMixin

# 用户-角色多对多关联表
user_role_table = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("app_user.id"), primary_key=True),
    Column("role_id", ForeignKey("role.id"), primary_key=True),
)


class User(IntPkMixin, Base):
    """平台用户。status: 1=启用 0=停用；must_change_password 支撑首启强制改密（DEP-07）。"""

    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)

    roles: Mapped[list["Role"]] = relationship(
        secondary=user_role_table, lazy="selectin"
    )
    scopes: Mapped[list["DataScope"]] = relationship(
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def role_codes(self) -> list[str]:
        """角色编码列表，供权限判断。"""
        return [r.code for r in self.roles]


class Role(IntPkMixin, Base):
    """内置角色（R-BIZ/R-DA/R-AD/R-AU/R-DEV），权限矩阵见需求 §2.2。"""

    __tablename__ = "role"

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(64))


class DataScope(IntPkMixin, Base):
    """用户数据范围（店铺/区域/部门），行级权限依据（FR-SEC-10）。"""

    __tablename__ = "data_scope"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id"))
    scope_type: Mapped[str] = mapped_column(String(32))  # shop / region / department
    scope_value: Mapped[str] = mapped_column(String(128))

    user: Mapped["User"] = relationship(back_populates="scopes")
