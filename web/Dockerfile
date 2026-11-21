ARG NODE_IMAGE=node:22-alpine
ARG NPM_REGISTRY=https://registry.npmmirror.com

FROM ${NODE_IMAGE} AS build

ARG NPM_REGISTRY
WORKDIR /app
ENV NPM_CONFIG_REGISTRY=${NPM_REGISTRY}

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80