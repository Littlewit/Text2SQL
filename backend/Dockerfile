# 后端服务镜像（DEP-01）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# pip 镜像源可经构建参数覆盖（国内网络提速）：--build-arg PIP_INDEX_URL=...
ARG PIP_INDEX_URL=https://pypi.org/simple

# 先装依赖再拷贝代码，利用 Docker 层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} .

COPY . .

# 迁移 + 启动入口（DEP-07：一键初始化；迁移幂等，可安全重复执行）
RUN chmod +x /app/entrypoint.sh && sed -i 's/\r$//' /app/entrypoint.sh

EXPOSE 8000

# entrypoint 先跑 Alembic 迁移再启动应用
CMD ["sh", "/app/entrypoint.sh"]
