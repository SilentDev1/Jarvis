FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd -r -u 10001 jarvis && mkdir -p /app/data /app/logs && chown -R jarvis /app
USER jarvis
EXPOSE 8765
CMD ["uvicorn","jarvis_home.app:app","--host","0.0.0.0","--port","8765"]

