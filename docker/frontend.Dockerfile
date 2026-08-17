# 前端镜像：Vite 打包 → nginx 托管静态文件并作统一入口反代
# 构建上下文为仓库根目录（与 backend/auth-server 一致），路径带 frontend/ 前缀

# ---- 构建阶段：npm ci + vite build（VITE_USE_MOCK 默认 false，走真实后端契约）----
FROM node:20-alpine AS build
WORKDIR /app
# 先拷依赖清单，利用层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 运行阶段：nginx 挂载反代配置 + 静态产物 ----
FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
