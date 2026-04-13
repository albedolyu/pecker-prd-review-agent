FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY *.py ./
COPY *.md ./

# 工作目录挂载点
VOLUME ["/workspace"]

# 默认入口
ENTRYPOINT ["python", "run_session.py"]
CMD ["--help"]
