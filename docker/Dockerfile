# Reference base for the dev-circuit-ultra strong-isolation setup.
# Install your coding agent (Claude Code / pi / Codex) in an extension of this image.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git openssh-client python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash dev \
    && useradd --create-home --shell /bin/bash archivist

WORKDIR /work
