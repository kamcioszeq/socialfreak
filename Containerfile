# Full image name for Podman without unqualified-search registries
FROM docker.io/library/python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5174
EXPOSE 8443
CMD ["python", "main.py"]
