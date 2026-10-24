from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from backend.auth_utils import get_current_user_id
from backend.models import User
from backend.extensions import db, socketio

# 创建一个新的蓝图对象
main_bp = Blueprint('main', __name__)

@main_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查端点，用于前端检测后端服务是否可用"""
    return jsonify({"status": "ok", "message": "Service is running"}), 200

@main_bp.route('/profile', methods=['GET'])
@jwt_required()
def profile():
    """一个受保护的路由，用于获取当前用户的个人信息"""
    current_user_id = get_current_user_id()
    user = db.session.get(User, current_user_id)
    
    if not user:
        return jsonify({"msg": "User not found"}), 404
        
    return jsonify({
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "avatar": user.avatar
    }), 200

@main_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    """获取所有用户的信息"""
    users = User.query.all()
    users_data = [{
        'id': user.id,
        'username': user.username,
        'role': user.role,
        'avatar': user.avatar
    } for user in users]
    return jsonify(users_data)

@main_bp.route('/sync-status', methods=['POST'])
@jwt_required()
def sync_user_status():
    """同步用户状态"""
    current_user_id = get_current_user_id()
    
    # 获取要同步的状态
    # 根据用户当前所在页面决定状态
    status = 'offline'  # 默认离线
    
    # 获取请求中的状态参数
    from flask import request
    data = request.get_json()
    if data and 'status' in data:
        status = data['status']
        
    # 通过WebSocket广播状态更新
    room_name = f'user_{current_user_id}'
    socketio.emit('status_update', {
        'user_id': current_user_id,
        'status': status
    }, room=room_name)
    
    # 同时广播给其他用户
    other_users = User.query.filter(User.id != current_user_id).all()
    for user in other_users:
        other_room = f'user_{user.id}'
        socketio.emit('status_update', {
            'user_id': current_user_id,
            'status': status
        }, room=other_room)
    
    return jsonify({"status": "success", "message": "状态已同步"}), 200 
