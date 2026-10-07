# A clean, reproducible environment for the tests and the benchmark. Build and check:
#   docker build -t navkit . && docker run --rm navkit
FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /work

# Metadata and the files the wheel includes first, so the dependency layer is cached
# until pyproject.toml or the package changes.
COPY pyproject.toml README.md LICENSE ./
COPY configs ./configs
COPY src ./src
RUN pip install -e ".[dev]"

COPY . .

# Default: the same test command CI runs.
CMD ["python", "-m", "pytest", "-q"]
