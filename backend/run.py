"""开发/部署统一启动入口（跨平台）。

为什么不用 `uvicorn` 命令直接启动：
uvicorn 0.36 在 Windows 上通过 loop_factory 强制使用 ProactorEventLoop，
而 psycopg 异步模式仅兼容 SelectorEventLoop（连接会直接报 InterfaceError）。
因此这里自建事件循环并驱动 uvicorn.Server，保证 Windows 本地开发可用；
Linux 容器内 uvicorn 默认即为 SelectorEventLoop，本文件行为一致。
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  —— 必须在设置事件循环策略之后导入


def main() -> None:
    # 依据当前策略创建 Selector 事件循环，并在此循环上运行 uvicorn 服务
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
