# 校园低碳行为管理系统 - 后端服务

## 项目简介

基于 Spring Boot 3.2.0 + JPA + MySQL 的校园低碳行为管理系统后端服务。

## 技术栈

- **框架**: Spring Boot 3.2.0
- **Java版本**: JDK 17
- **数据库**: MySQL 8.0+
- **ORM**: Spring Data JPA
- **认证**: JWT (JSON Web Token)
- **构建工具**: Maven

## 项目结构

```
backend/
├── src/
│   ├── main/
│   │   ├── java/
│   │   │   └── com/campus/lowcarbon/
│   │   │       ├── LowcarbonSystemApplication.java    # 主启动类
│   │   │       ├── common/                             # 通用类
│   │   │       │   └── Result.java                     # 统一响应结果
│   │   │       ├── config/                             # 配置类
│   │   │       │   └── CorsConfig.java                 # 跨域配置
│   │   │       ├── controller/                         # 控制器层
│   │   │       │   └── AuthController.java             # 认证控制器
│   │   │       ├── dto/                                # 数据传输对象
│   │   │       │   ├── LoginRequest.java               # 登录请求DTO
│   │   │       │   ├── LoginResponse.java             # 登录响应DTO
│   │   │       │   └── RegisterRequest.java           # 注册请求DTO
│   │   │       ├── entity/                             # 实体类
│   │   │       │   ├── User.java                       # 用户实体
│   │   │       │   └── StudentInfo.java                # 学生信息实体
│   │   │       ├── exception/                          # 异常处理
│   │   │       │   ├── BusinessException.java         # 业务异常
│   │   │       │   └── GlobalExceptionHandler.java    # 全局异常处理器
│   │   │       ├── repository/                        # 数据访问层
│   │   │       │   ├── UserRepository.java             # 用户Repository
│   │   │       │   └── StudentInfoRepository.java     # 学生信息Repository
│   │   │       ├── service/                            # 业务逻辑层
│   │   │       │   └── AuthService.java                # 认证服务
│   │   │       └── util/                               # 工具类
│   │   │           └── JwtUtil.java                     # JWT工具类
│   │   └── resources/
│   │       └── application.yml                         # 应用配置文件
│   └── test/                                            # 测试代码
└── pom.xml                                              # Maven配置文件
```

## 环境要求

- JDK 17+
- Maven 3.6+
- MySQL 8.0+
- 数据库已创建并执行了 `docs/schema.sql` 脚本

## 配置说明

### 数据库配置

编辑 `src/main/resources/application.yml`：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/campus_lowcarbon_db?useUnicode=true&characterEncoding=utf8&useSSL=false&serverTimezone=Asia/Shanghai
    username: ${DB_USERNAME:root}
    password: ${DB_PASSWORD:}
```

### JWT配置

```yaml
jwt:
  secret: ${JWT_SECRET:}  # 本地JWT密钥
  expiration: 1800000  # Token过期时间（30分钟，单位：毫秒）
```

## 运行项目

### 1. 确保数据库已创建

执行 `docs/schema.sql` 脚本创建数据库和表。

### 2. 编译项目

```bash
cd backend
mvn clean compile
```

### 3. 运行项目

```bash
mvn spring-boot:run
```

或者使用IDE直接运行 `LowcarbonSystemApplication.java`。

### 4. 访问接口

服务启动后，访问地址：`http://localhost:8080/api`

## API接口文档

### 1. 用户登录

**接口地址**: `POST /api/auth/login`

**请求参数**:
```json
{
  "studentId": "20210001",
  "password": "123456"
}
```

**响应示例**:
```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "role": "student",
    "userInfo": {
      "name": "张三",
      "studentId": "20210001",
      "avatar": ""
    }
  }
}
```

### 2. 用户注册

**接口地址**: `POST /api/auth/register`

**请求参数**:
```json
{
  "studentId": "20210001",
  "username": "张三",
  "password": "123456"
}
```

**响应示例**:
```json
{
  "code": 200,
  "message": "注册成功，请登录",
  "data": null
}
```

## 注意事项

1. **密码存储**: 本项目采用明文存储密码，仅用于毕业设计演示，生产环境必须加密。

2. **学号验证**: 注册时需要验证学号是否存在于 `student_info` 表中。

3. **管理员账号**: 管理员账号无法通过注册获得，需在数据库中手动插入。

4. **Token使用**: 前端需要在请求头中携带Token：`Authorization: Bearer {token}`

5. **跨域配置**: 已配置跨域支持，允许前端访问。

## 开发说明

### 统一响应格式

所有接口统一使用 `Result<T>` 作为响应格式：

```java
{
  "code": 200,        // 状态码：200-成功，其他-失败
  "message": "操作成功",  // 响应消息
  "data": {}          // 响应数据
}
```

### 异常处理

- `BusinessException`: 业务异常，返回自定义错误消息
- `MethodArgumentNotValidException`: 参数校验异常，返回校验错误消息
- `Exception`: 其他异常，返回通用错误消息

### 代码规范

- 所有类和方法都添加了中文注释
- 使用 Lombok 简化代码
- 遵循 RESTful API 设计规范
- 使用 JPA 进行数据库操作

## 后续开发计划

- [ ] 实现JWT拦截器，保护需要认证的接口
- [ ] 实现用户信息查询接口
- [ ] 实现打卡相关接口
- [ ] 实现积分和称号相关接口
- [ ] 实现管理员审核接口

