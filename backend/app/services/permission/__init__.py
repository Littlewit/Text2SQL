"""权限服务包：行级权限 AST 改写（FR-SEC-10~14）+ 复验。"""

from app.services.permission.rewriter import rewrite_row_permissions

__all__ = ["rewrite_row_permissions"]
