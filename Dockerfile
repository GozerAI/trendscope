FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e ".[api]"

EXPOSE 8002

CMD ["uvicorn", "trendscope.app:app", "--host", "0.0.0.0", "--port", "8002"]
