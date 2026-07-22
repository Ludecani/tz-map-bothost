FROM python:3.12-slim
WORKDIR /app
ENV PORT=3000
EXPOSE 3000 8080
COPY server.py .
COPY requirements.txt .
COPY bot.py .
RUN mkdir -p build data docs
COPY index.html ./build/index.html
COPY sync-mirror.json ./sync-mirror.json
COPY sync-api.json ./sync-api.json
COPY docs/sync-mirror.json ./docs/sync-mirror.json
COPY docs/sync-api.json ./docs/sync-api.json
COPY sync-api.json ./build/sync-api.json
CMD ["python", "-u", "server.py"]
