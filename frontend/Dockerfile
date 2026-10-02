# Frontend Dockerfile
FROM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80 AS base
WORKDIR /app
# The Node distribution's bundled npm has separate dependency advisories.
# Keep both install and build tooling aligned with tooling/toolchain.json.
RUN npm install --global npm@11.20.0 && npm cache clean --force

# Install dependencies
FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci
RUN node -e "const v=require('sharp').versions.heif.split('.').map(Number); if(v[0]<1||(v[0]===1&&(v[1]<23||(v[1]===23&&v[2]<2)))) throw Error('Unpatched libheif')"

# Build the application
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_DEV_APP_URL
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG API_BASE_URL=""
ENV API_BASE_URL=$API_BASE_URL
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_DEV_APP_URL=$NEXT_PUBLIC_DEV_APP_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_APP_REVISION=unknown
ENV NEXT_PUBLIC_APP_REVISION=$NEXT_PUBLIC_APP_REVISION
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Development runtime
FROM base AS dev
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
CMD ["npm", "run", "dev"]

# Production runtime
FROM base AS runtime
ARG APP_REVISION=unknown
LABEL org.opencontainers.image.revision=$APP_REVISION
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs && \
    apk add --no-network ca-certificates-bundle && \
    apk del apk-tools zlib && \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /opt/yarn-v1.22.22 && \
    rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
