FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy both the existing MCP server and the optional monitor modules.
COPY . .

ENV MCP_TRANSPORT=sse
ENV PORT=8000
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# The existing MCP service remains the default container command.
# Run the optional monitor as a separate Render service with:
# python monitor_worker.py
CMD ["python", "server.py"]
