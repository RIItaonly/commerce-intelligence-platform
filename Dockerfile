# 端到端电商智能决策平台：单镜像同时支持 API 与 Streamlit 看板
# 构建:  docker build -t commerce-intelligence .
# API:   docker run -p 8000:8000 commerce-intelligence
# 看板:  docker run -p 8501:8501 commerce-intelligence streamlit run dashboard/app.py --server.address 0.0.0.0
FROM python:3.8-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码与 SQL（数据/模型产物通过挂载卷注入，不打进镜像）
COPY src ./src
COPY dashboard ./dashboard
COPY sql ./sql
COPY tests ./tests
COPY reports ./reports

EXPOSE 8000 8501

# 默认启动 API；看板用 command 覆盖即可
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
