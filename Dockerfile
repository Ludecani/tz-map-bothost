FROM python:3.12-slim
WORKDIR /app
COPY server.py .
RUN mkdir -p build
COPY index.html ./build/index.html
CMD ["python", "-u", "server.py"]
