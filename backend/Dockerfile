FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.cpu.txt requirements.runtime.txt ./

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --requirement requirements.cpu.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --requirement requirements.runtime.txt

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-deps --no-build-isolation . \
    && mkdir -p /app/data/faiss /app/data/models \
    && chown -R app:app /app/data

LABEL org.opencontainers.image.title="AI Hotel Customer Support Bot Backend" \
      org.opencontainers.image.version="0.1.0"

USER app

EXPOSE 8000

CMD ["uvicorn", "hotel_bot.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
