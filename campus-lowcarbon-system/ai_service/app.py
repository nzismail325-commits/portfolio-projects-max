# -*- coding: utf-8 -*-
"""
=============================================================================
低碳校园智能问答服务 (AI Service) - 主程序入口
=============================================================================

技术架构: Generative RAG (生成式检索增强)
分层结构:
    - core/         : AI 核心调用层（大模型封装）
    - services/     : 业务逻辑层（RAG、防作弊）
    - routers/      : API 接口层（Flask Blueprint）
    - app.py        : 主程序入口

启动方式:
    python app.py

=============================================================================
"""

from flask import Flask
from flask_cors import CORS

from routers import api_bp
from services import chat_service
from services.config_service import refresh_all_configs

# =============================================================================
# Flask 应用初始化
# =============================================================================
app = Flask(__name__)
CORS(app)  # 启用跨域支持，允许前端调用

# =============================================================================
# 注册路由蓝图
# =============================================================================
app.register_blueprint(api_bp)

# =============================================================================
# 应用启动
# =============================================================================
print("\n" + "="*60)
print("[INFO] 低碳校园智能问答服务 (Generative RAG)")
print("="*60)

# 预加载知识库和 TF-IDF 模型（单例模式，只加载一次）
chat_service.init_model()

# 预加载场景配置（从Spring Boot后端获取）
print("[INFO] 正在加载场景配置...")
try:
    refresh_all_configs()
    print("[OK] 场景配置加载成功")
except Exception as e:
    print(f"[WARN] 场景配置加载失败: {e}，将在验证时尝试获取")

print("="*60)
print("[OK] 服务就绪，监听端口 5000")
print("="*60 + "\n")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
