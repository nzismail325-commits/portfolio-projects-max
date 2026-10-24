import uuid
import logging
from flask import Blueprint, request, jsonify
from backend.models import User
from backend.extensions import db, socketio
from flask_jwt_extended import create_access_token, get_jti

# 创建一个蓝图对象
auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    用户登录接口
    """
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"msg": "请求中缺少用户名或密码"}), 400

    username = data.get('username')
    password = data.get('password')
    # 获取设备ID，如果没有提供则生成一个新的
    device_id = data.get('device_id') or str(uuid.uuid4())

    # 从数据库中查找用户
    user = User.query.filter_by(username=username).first()

    # 校验用户和密码
    if user is None or not user.check_password(password):
        return jsonify({"msg": "用户名或密码错误"}), 401

    # 在更新jti之前，获取旧的jti（如果有的话）
    old_jti = user.current_jti
    
    # 检查是否是同一设备的再次登录
    same_device = user.device_id == device_id

    # 创建新的JWT和jti
    access_token = create_access_token(identity=str(user.id), fresh=True)
    new_jti = get_jti(access_token)

    # 将新的jti和设备ID存入数据库
    user.current_jti = new_jti
    user.device_id = device_id
    db.session.commit()

    # 只有在不同设备登录时，才发送强制下线通知
    if old_jti and not same_device:
        room_name = f'user_{user.id}'
        # 我们把旧的 jti 发过去，让前端可以精确判断是不是自己该下线
        socketio.emit('force_logout', {'jti': old_jti}, room=room_name)
        logger.info("向房间 %s 发送了 force_logout 指令", room_name)
        logger.info("检测到不同设备登录: 用户ID=%s", user.id)

        # 新增：主动向伙伴通知该用户的旧设备离线状态
        # 1. 查找用户的伙伴
        other_user = User.query.filter(User.id != user.id).first()
        if other_user:
            # 2. 构建伙伴的房间名
            partner_room = f'user_{other_user.id}'
            # 3. 发送状态更新，告知该用户已离线
            # 这样伙伴就能立即知道用户已被挤下线
            socketio.emit('status_update', {'user_id': user.id, 'status': 'offline'}, room=partner_room)
            logger.info("向伙伴 %s 发送了用户 %s 的离线状态", other_user.id, user.id)
            
            # 4. 这里我们直接使用emit更新状态，不需要修改全局变量

    return jsonify(access_token=access_token, user_id=user.id) 
