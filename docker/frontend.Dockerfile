# ============================================================
# 前端 Dockerfile - Vue3 + Vite 构建 + Nginx 托管
# 多阶段构建: 构建阶段生成静态文件, 运行阶段用 Nginx 托管
# ============================================================

# ---- 阶段1: Node 构建 ----
FROM node:20-alpine AS builder

WORKDIR /app

# 国内 npm 镜像源（加速依赖安装）
RUN npm config set registry https://registry.npmmirror.com

# 复制依赖文件并安装（利用 Docker 缓存）
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# 复制源码并构建
COPY . .

# 构建参数：API 基础 URL
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---- 阶段2: Nginx 运行时 ----
FROM nginx:1.25-alpine AS runtime

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置（支持 SPA 路由 + API 反向代理）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -q -O /dev/null http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
