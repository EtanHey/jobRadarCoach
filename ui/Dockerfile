FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 1001 radar && adduser -S -u 1001 -G radar radar
COPY --from=build --chown=radar:radar /app/.next/standalone ./
COPY --from=build --chown=radar:radar /app/.next/static ./.next/static
USER radar
EXPOSE 3000
CMD ["node", "server.js"]
