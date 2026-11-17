# A clean, reproducible environment for the tests and the benchmark. Build and check:
#   docker build -t navkit . && docker run --rm navkit
# Pinned by digest, so the image a build uses cannot change under it. The tag says what the digest is;
# Dependabot proposes the next digest, and the container job in CI rebuilds the image to check it.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
