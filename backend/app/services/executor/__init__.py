"""查询执行服务包：只读执行器（FR-SEC-30/32/35）。"""

from app.services.executor.runner import execute_readonly

__all__ = ["execute_readonly"]
