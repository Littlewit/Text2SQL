# 后端服务镜像（DEP-01）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖再拷贝代码，利用 Docker 层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 8000

# 使用 run.py 启动：跨平台处理事件循环兼容性（见 run.py 说明）
CMD ["python", "run.py"]
