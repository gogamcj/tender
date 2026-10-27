# 웹 화면 빌드 후 nginx 로 제공. /api 요청은 같은 출처로 백엔드에 넘긴다(SameSite=Strict 쿠키 유지).
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
