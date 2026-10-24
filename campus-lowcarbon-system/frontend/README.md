# 智能低碳行为管理系统 - 前端

## 技术栈

- **框架**: Vue 3 (Composition API with Script Setup)
- **构建工具**: Vite
- **UI 组件库**: Element Plus
- **路由**: Vue Router 4
- **状态管理**: Pinia
- **HTTP 客户端**: Axios
- **CSS**: Scoped CSS

## 项目结构

```
frontend/
├─ src/
│  ├─ api/                   # API 接口
│  │  └─ auth.js             # 认证相关接口
│  ├─ components/            # 全局组件
│  ├─ router/                # 路由配置
│  │  └─ index.js
│  ├─ utils/                 # 工具类
│  │  └─ request.js          # Axios 封装
│  ├─ views/                 # 页面视图
│  │  ├─ login/              # 登录注册页
│  │  │  └─ index.vue
│  │  └─ dashboard/          # 仪表板
│  │     └─ index.vue
│  ├─ App.vue                # 根组件
│  └─ main.js                # 入口文件
├─ index.html                # HTML 模板
├─ vite.config.js            # Vite 配置
└─ package.json              # 依赖管理
```

## 快速开始

### 1. 安装依赖

```bash
npm install
# 或
yarn install
# 或
pnpm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173 查看项目。

### 3. 构建生产版本

```bash
npm run build
```

## 功能特性

### 当前已实现

- ✅ 用户登录/注册页面
  - 左右分栏设计
  - 深绿色渐变品牌展示区
  - 表单验证（Element Plus Form）
  - 密码一致性校验
  - 登录/注册模式切换
  - 模拟 API 调用（1秒延迟）
  
- ✅ 路由配置
  - 登录页 (`/login`)
  - 仪表板 (`/dashboard`)
  - 路由守卫（简单版 Token 验证）

- ✅ Axios 封装
  - 请求/响应拦截器
  - 统一错误处理
  - Token 自动注入

### 待实现功能

根据毕设大纲，后续需要实现：

1. **学生端功能**
   - 智能打卡上传（5种低碳场景）
   - 个人碳积分画像（ECharts 可视化）
   - 积分权益商城
   - AI 低碳顾问聊天

2. **管理员端功能**
   - 低碳规则配置中心
   - 异常复核工作台
   - 全局数据看板

## 开发规范

1. **组件命名**: 使用 PascalCase
2. **文件命名**: 使用 kebab-case
3. **注释**: 强制使用中文注释
4. **代码风格**: 
   - 使用 Composition API (Script Setup)
   - 优先使用 `const` 而非 `let`
   - 使用 ES6+ 语法

## API 代理配置

开发环境下，所有 `/api/*` 请求会被代理到 `http://localhost:8080`（后端 Spring Boot 服务）。

配置位置：`vite.config.js`

## 注意事项

- 当前登录/注册为**模拟实现**（使用 `setTimeout` 模拟延迟）
- 正式环境需要将注释掉的真实 API 调用代码启用
- Token 存储在 `localStorage` 中（生产环境建议使用更安全的方式）

## 联系方式

如有问题，请联系项目负责人。
