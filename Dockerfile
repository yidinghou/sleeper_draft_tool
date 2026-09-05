# The queue builder, served for a phone. See python/scripts/snake/queue_server.py.
#
# A Dockerfile rather than nixpacks because package.json sits at the repo root:
# nixpacks reads that and builds a Node app, and this service is Python. There
# are no Python dependencies -- the server is stdlib only -- so there is no
# install step at all, just a copy.
FROM python:3.12-slim

WORKDIR /app

# Only what the server actually reads: its own code, and the prebuilt payload.
# The VORP pipeline's inputs (data/snake/vorp-snake-*.csv, data/adp-*.csv) are
# gitignored and deliberately absent -- the payload is built on the laptop and
# committed, so this image never needs a board.
COPY python/ ./python/
COPY data/snake/queue-payload-*.json ./data/snake/

ENV PORT=8771 PREFS_DIR=/data
EXPOSE 8771

CMD ["python3", "python/scripts/snake/queue_server.py"]
