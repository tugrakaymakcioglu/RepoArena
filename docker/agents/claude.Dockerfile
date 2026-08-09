FROM node:22-bookworm-slim

ARG CLAUDE_VERSION=latest
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && npm install --global "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
    && mkdir -p /home/node/.claude \
    && chown -R node:node /home/node/.claude \
    && rm -rf /var/lib/apt/lists/*

USER node
WORKDIR /workspace
