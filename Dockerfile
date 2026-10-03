FROM python:3.13-slim
WORKDIR /app
COPY . /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000
ENV HOST=0.0.0.0
RUN python3 -m py_compile server.py
EXPOSE 10000
CMD ["sh", "-c", "python3 server.py --host ${HOST} --port ${PORT} --db ${SKILLFORGE_DB_PATH:-/data/skillforge.db}"]
