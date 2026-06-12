FROM python:3.11-slim

# Tizim bog'liqliklari (asyncssh/cryptography uchun build, git, va Claude Code CLI uchun Node).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl build-essential libffi-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — claude-agent-sdk haqiqiy agent ishga tushirish uchun talab qiladi.
RUN npm install -g @anthropic-ai/claude-code || true

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

# Agentlar ish katalogi (ilova kodidan ajratilgan).
RUN mkdir -p /workspace
ENV ORCHESTRA_WORKDIR=/workspace
ENV PYTHONUNBUFFERED=1

# Default: orchestrator. docker-compose har servis uchun CMD'ni ustun yozadi.
CMD ["python", "-m", "orchestra.cli", "run"]
