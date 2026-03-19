# 第一阶段：构建环境
FROM python:3.12-slim AS builder

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 设置工作目录
WORKDIR /app

# 先拷贝依赖文件以利用 Docker 缓存
COPY pyproject.toml .
# 强制生成锁定文件
RUN uv sync --no-install-project

# 拷贝源代码
COPY . .

# 执行同步
RUN uv sync

# 第二阶段：运行时环境
FROM python:3.12-slim

WORKDIR /app

# 从构建阶段拷贝虚拟环境
COPY --from=builder /app/.venv /app/.venv
# 拷贝源代码
COPY . .

# 设置环境变量，确保 Python 使用虚拟环境并开启无缓冲输出
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# 暴露端口
EXPOSE 8000

# 启动脚本：先重置密码，再启动服务
CMD ["sh", "-c", "python reset_pwd.py && python main.py"]
