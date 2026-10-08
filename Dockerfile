# A clean, reproducible environment for the tests and the benchmark. Build and check:
#   docker build -t navkit . && docker run --rm navkit
# Pinned by digest, so the image a build uses cannot change under it. The tag says what the digest is;
# Dependabot proposes the next digest, and the container job in CI rebuilds the image to check it.
FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c

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
