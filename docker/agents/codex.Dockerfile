FROM node:22-bookworm-slim

ARG CODEX_VERSION=latest
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && mkdir -p /home/node/.codex \
    && chown -R node:node /home/node/.codex \
    && rm -rf /var/lib/apt/lists/*

USER node
WORKDIR /workspace
