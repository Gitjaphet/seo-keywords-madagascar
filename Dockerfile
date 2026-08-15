FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv sync --no-dev

COPY . .

ENTRYPOINT ["uv", "run", "seo-keywords"]
CMD ["--help"]
