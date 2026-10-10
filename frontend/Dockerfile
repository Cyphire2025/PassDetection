# Frontend Dockerfile
FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS base
WORKDIR /app
# The Node distribution's bundled npm has separate dependency advisories.
# Keep both install and build tooling aligned with tooling/toolchain.json.
COPY scripts/patch-npm-toolchain.mjs ./scripts/patch-npm-toolchain.mjs
COPY tooling/npm-security ./tooling/npm-security
RUN npm install --global npm@11.20.0 && \
    node scripts/patch-npm-toolchain.mjs /usr/local/lib/node_modules/npm && \
    npm cache clean --force

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
    rm -rf /app/tooling/npm-security /app/scripts/patch-npm-toolchain.mjs && \
    rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Verify the final filesystem, including files copied by standalone tracing.
RUN test -f /app/server.js && test -d /app/.next/static && \
    test ! -e /app/tooling/npm-security && test ! -e /app/scripts/patch-npm-toolchain.mjs

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
