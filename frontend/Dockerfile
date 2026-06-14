# ---- Stage 1: build the Vite bundle ----
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# Build the static bundle. VITE_API_BASE is empty by default so the app makes
# same-origin /api + /health calls, which nginx proxies to the backend.
COPY . .
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ---- Stage 2: serve with nginx ----
FROM nginx:1.27-alpine AS runtime

# Templated SPA + reverse-proxy config. The nginx image runs envsubst over
# files in /etc/nginx/templates at startup; NGINX_ENVSUBST_FILTER limits the
# substitution to ${BACKEND_URL} so nginx runtime vars ($host, $remote_addr,
# $uri, ...) are left intact.
COPY default.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_URL=http://backend:8000
ENV NGINX_ENVSUBST_FILTER=BACKEND_URL

# Static assets produced by the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
