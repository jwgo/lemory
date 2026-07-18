# Lemory — self-hosted local memory middleware.
#
#   docker build -t lemory .
#   docker run -p 8377:8377 -v /path/to/vault:/vault -v lemory-models:/root/.cache lemory
#
# Keyless by default (Korean-tuned e5 ONNX embeddings download once into the
# models volume). Pass -e GEMINI_API_KEY=... for cloud answers. The container
# binds 0.0.0.0 internally; publish the port to localhost only
# (-p 127.0.0.1:8377:8377) OR set LEMORY_API_TOKEN and expose it — remote
# clients without the Bearer token are refused by design.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[local]"

VOLUME /vault
EXPOSE 8377
ENV LEMORY_VAULT=/vault
CMD ["lemory", "serve", "--host", "0.0.0.0", "--port", "8377"]
