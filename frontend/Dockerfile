# Stage 1: build the React app
FROM node:20-alpine AS build
WORKDIR /app
# Copy manifests first so npm ci is cached unless dependencies change.
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve the built assets through nginx
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
