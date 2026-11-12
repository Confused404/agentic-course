# Sandbox image for shopdev's shell (Node 03 §6). Dependencies only: the workspace is mounted at run time.
# Build:  docker build -t agentic-course/shopdev:latest -f docker/shopdev.Dockerfile .
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /tmp/build/pyproject.toml
# Install only the declared dependencies (no project source), so the image is reusable across commits.
RUN python - <<'PY'
import tomllib, subprocess, sys
p = tomllib.load(open("/tmp/build/pyproject.toml", "rb"))["project"]
deps = p["dependencies"] + p["optional-dependencies"]["dev"]
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *deps])
PY
WORKDIR /work
ENV PYTHONPATH=/work
