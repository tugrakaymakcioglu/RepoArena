FROM node:22-bookworm-slim

ARG OPENCODE_VERSION=latest
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && npm install --global "opencode-ai@${OPENCODE_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

USER node
WORKDIR /workspace
