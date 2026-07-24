FROM node:22.20.0-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM caddy:2.11-alpine

COPY Caddyfile Caddyfile.production app-routes.caddy /etc/caddy/
COPY --from=build /app/dist /srv

RUN addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app \
    && setcap -r /usr/bin/caddy \
    && chown -R app:app /srv /etc/caddy /config /data
USER app

EXPOSE 8080 8090 8443

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget --quiet --spider http://127.0.0.1:8090/healthz || exit 1

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
