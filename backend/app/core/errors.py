"""统一业务异常与响应包络（§6.4）。

所有 API 错误统一为 {code, message, data, trace_id} 结构；
面向用户的消息必须是可理解的中文（NFR-O-02：技术细节只进日志）。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.tracing import get_trace_id


class AppError(Exception):
    """业务异常基类：code 为业务错误码，status_code 为 HTTP 状态码。"""

    def __init__(self, code: int, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def ok(data=None) -> dict:
    """成功响应包络。"""
    return {"code": 0, "message": "ok", "data": data, "trace_id": get_trace_id()}


def error_response(code: int, message: str, status_code: int) -> JSONResponse:
    """失败响应包络（供异常处理器使用）。"""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "data": None, "trace_id": get_trace_id()},
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI 异常处理器：AppError → 统一包络。

    签名声明为 Exception 以满足 starlette ExceptionHandler 的参数逆变要求，
    运行时仅由 add_exception_handler(AppError, ...) 注册，此处断言收窄。
    """
    assert isinstance(exc, AppError), f"unexpected exception type: {type(exc).__name__}"
    return error_response(exc.code, exc.message, exc.status_code)
