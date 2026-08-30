# Cloud Run image for the console. Same reasoning as backend/Dockerfile: scale
# to zero makes cold starts the common case, so the runtime layer carries the
# built server and nothing else — no node_modules, no source, no toolchain.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `output: "standalone"` in next.config.mjs is what makes the runtime stage
# possible: it traces the server's actual imports into .next/standalone.
RUN npm run build

FROM node:20-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=8080 \
    HOSTNAME=0.0.0.0

# The standalone bundle carries its own minimal node_modules. Static assets and
# public/ are not traced into it and have to be copied alongside, or every page
# renders unstyled.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

RUN adduser --disabled-password --gecos "" --uid 10001 appuser && \
    chown -R appuser /app
USER appuser

EXPOSE 8080

# Rewrites in next.config.mjs are resolved when this server boots, so
# API_BASE_URL is read at runtime and Cloud Run can set it per environment.
CMD ["node", "server.js"]
