FROM ghcr.io/hydra-db/hydradb:0.4.0

USER root
RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    PORT=7860

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --python 3.12
COPY baton baton
COPY app app
COPY agent agent
COPY eval eval
COPY data data
COPY results results
COPY scripts scripts
RUN chmod -R a+rX /app /opt && chown -R 1000:1000 /app/results

USER 1000
EXPOSE 7860
ENTRYPOINT ["/app/scripts/serve.sh"]
