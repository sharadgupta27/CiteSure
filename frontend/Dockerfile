# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f frontend/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY openapi.yaml ./openapi.yaml
WORKDIR /app/frontend
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run gen:api && npm run build

# The "unprivileged" nginx image runs as a normal user (not root) and listens on 8080: if the web server were ever
# compromised, the attacker would not be root inside the container (Trivy DS-0002).
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
