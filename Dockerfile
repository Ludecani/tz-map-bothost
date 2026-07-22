FROM python:3.12-slim
WORKDIR /app
ENV PORT=3000
EXPOSE 3000 8080
COPY server.py .
COPY requirements.txt .
COPY bot.py .
RUN mkdir -p build data
COPY index.html ./build/index.html
COPY sync-mirror.json ./sync-mirror.json
COPY docs/sync-mirror.json ./docs/sync-mirror.json
CMD ["python", "-u", "server.py"]
