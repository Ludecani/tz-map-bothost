FROM python:3.12-slim
WORKDIR /app
COPY server.py .
COPY build/ ./build/
CMD ["python", "-u", "server.py"]
