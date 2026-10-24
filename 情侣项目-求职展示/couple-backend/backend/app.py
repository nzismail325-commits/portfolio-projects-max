import os
import datetime
import logging
from flask import Flask, request, send_from_directory
from flask_cors import CORS
from flask_migrate import Migrate

from backend.models import User, Message, LoveGarden, GardenAction
from backend.config import Config
from backend.extensions import db, jwt, socketio
from backend.database_init import initialize_database
from backend.routes.auth import auth_bp
from backend.routes.main import main_bp
from backend.routes.diary import diary_bp
from backend.routes.chat import chat_bp
from backend.routes.upload import upload_bp
from backend.routes.user import user_bp
from backend.routes.garden import garden_bp
from backend.routes.music import music_bp  # 导入新的音乐蓝图
from backend.services.garden_scheduler import background_scheduler_loop

logger = logging.getLogger(__name__)

def create_app():
    """
    创建并配置Flask应用实例。
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/api/*": {"origins": "*"}}) # 允许/api/开头的跨域请求

    # 确保上传文件夹存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['AVATAR_UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_MUSIC'], exist_ok=True)

    # ---> 新增配置: 上传文件夹 <---
    # 设置上传文件的基路径
    UPLOAD_BASE_FOLDER = app.config['UPLOAD_BASE_FOLDER']
    # 为不同类型的文件设置具体的子文件夹
    app.config['UPLOAD_FOLDER_AVATARS'] = os.path.join(UPLOAD_BASE_FOLDER, 'avatars')
    app.config['UPLOAD_FOLDER_DIARY'] = os.path.join(UPLOAD_BASE_FOLDER, 'diary_images')

    # 确保所有上传目录都存在
    os.makedirs(app.config['UPLOAD_FOLDER_AVATARS'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_DIARY'], exist_ok=True)

    # --- 初始化扩展 ---
    db.init_app(app)
    jwt.init_app(app)
    # 为socketio配置更全面的CORS支持, 并明确指定async_mode
    socketio.init_app(app, 
                     async_mode=app.config['SOCKET_ASYNC_MODE'],
                     cors_allowed_origins="*",
                     ping_timeout=app.config['SOCKET_PING_TIMEOUT'],
                     ping_interval=app.config['SOCKET_PING_INTERVAL'])
    
    # 新增：初始化 Migrate
    migrate = Migrate(app, db)

    initialize_database(app)

    # --- 注册蓝图 ---
    # from .routes.main import main as main_blueprint
    # app.register_blueprint(main_blueprint)
    
    # 所有认证相关的路由都会有 /api/auth 的前缀
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    # 其他核心功能的路由将有 /api 的前缀
    app.register_blueprint(main_bp, url_prefix='/api')
    # 注册日记蓝图，所有日记相关的路由都会有 /api 的前缀
    app.register_blueprint(diary_bp, url_prefix='/api')
    # 注册聊天蓝图
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    # 新增：注册上传蓝图
    app.register_blueprint(upload_bp, url_prefix='/api/upload')
    # 新增：注册用户蓝图
    app.register_blueprint(user_bp, url_prefix='/api/user')
    # 新增：注册花园蓝图
    app.register_blueprint(garden_bp, url_prefix='/api/garden')
    app.register_blueprint(music_bp, url_prefix='/api/music') # 注册音乐蓝图

    # --- 启动定时任务 ---
    # 使用 socketio.start_background_task 来确保任务在gevent环境中安全运行
    socketio.start_background_task(background_scheduler_loop, app)

    # --- JWT Blocklist 配置 ---
    # 这个回调函数会在每次有受保护的请求时运行
    # 它的作用是检查当前token的jti是否还存在于数据库中
    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        user_id = int(jwt_payload["sub"])
        # 使用新的、推荐的方法来获取用户，避免潜在的缓存问题
        user = db.session.get(User, user_id)
        # 如果数据库中没有jti记录，或者jti与数据库中的不匹配
        # 则说明token已失效（比如用户在别处登录了）
        return user is None or user.current_jti is None or user.current_jti != jti

    # 新增：用于提供上传文件的访问路由
    @app.route('/uploads/chat_images/<filename>')
    def uploaded_file(filename):
        response = send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        # 添加CORS头，允许任何来源访问这些静态资源
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    # 新增：用于提供头像文件的访问路由
    @app.route('/uploads/avatars/<filename>')
    def uploaded_avatar_file(filename):
        response = send_from_directory(app.config['AVATAR_UPLOAD_FOLDER'], filename)
        # 添加CORS头，允许任何来源访问这些静态资源
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    # 新增：用于提供音乐文件的访问路由
    @app.route('/uploads/music/<filename>')
    def uploaded_music_file(filename):
        response = send_from_directory(app.config['UPLOAD_FOLDER_MUSIC'], filename)
        # 添加CORS头，允许任何来源访问这些静态资源
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    # ---> 新增配置: 设置静态文件路由 <---
    # 创建一个路由，让前端可以访问 uploads 文件夹中的内容
    @app.route('/uploads/<path:filename>')
    def uploaded_file_base(filename):
        return send_from_directory(app.config['UPLOAD_BASE_FOLDER'], filename)

    return app

# --- 应用实例化和命令注册 ---
app = create_app()

# --- 聊天相关状态管理 ---
# 用一个字典来跟踪用户是否在聊天页面中
# 键是 user_id, 值是 True/False
users_in_chat = {}
# 新增：用于从 sid 映射到 user_id，方便在断开连接时查找
sid_to_user = {}
chat_user_sids = {}
garden_user_sids = {}
sid_chat_users = {}
sid_garden_users = {}

# --- 花园相关状态管理 ---
# 用一个字典来跟踪用户是否在花园页面中
users_in_garden = {}

def normalize_user_id(user_id):
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None

def mark_user_online(user_sids, sid_users, user_id):
    user_sids.setdefault(user_id, set()).add(request.sid)
    sid_users[request.sid] = user_id
    sid_to_user[request.sid] = user_id

def mark_user_offline(user_sids, sid_users, user_id):
    user_sids.get(user_id, set()).discard(request.sid)
    if user_id in user_sids and not user_sids[user_id]:
        del user_sids[user_id]
    sid_users.pop(request.sid, None)
    if request.sid not in sid_chat_users and request.sid not in sid_garden_users:
        sid_to_user.pop(request.sid, None)

def is_user_online(user_sids, user_id):
    return bool(user_sids.get(user_id))

# --- WebSocket 事件处理 ---
@socketio.on('connect')
def handle_connect():
    logger.info('客户端已连接')

@socketio.on('join_room')
def handle_join_room(data):
    # 此处应有JWT验证逻辑，为简化暂时省略
    user_id = normalize_user_id(data.get('user_id'))
    if user_id:
        from flask_socketio import join_room
        room = f'user_{user_id}'
        join_room(room)
        sid_to_user[request.sid] = user_id
        logger.info('客户端已加入房间: %s', room)
        return {'ok': True, 'room': room}
    return {'ok': False, 'error': 'invalid_user_id'}

# 新增：用户进入聊天页
@socketio.on('enter_chat')
def handle_enter_chat(data):
    user_id = normalize_user_id(data.get('user_id'))
    if user_id:
        mark_user_online(chat_user_sids, sid_chat_users, user_id)
        users_in_chat[user_id] = True
        logger.info('用户 %s (SID: %s) 进入了聊天页面', user_id, request.sid)
        
        # 通知对方自己已上线
        other_user = User.query.filter(User.id != user_id).first()
        if other_user:
            socketio.emit('status_update', {'user_id': user_id, 'status': 'online'}, room=f'user_{other_user.id}')
            
            # 同时，告诉自己对方的在线状态
            is_partner_online = is_user_online(chat_user_sids, other_user.id)
            socketio.emit('status_update', {'user_id': other_user.id, 'status': 'online' if is_partner_online else 'offline'}, room=f'user_{user_id}')

# 新增：通用状态更新处理器
@socketio.on('status_update')
def handle_status_update(data):
    user_id = normalize_user_id(data.get('user_id'))
    status = data.get('status') # 'online' or 'offline'
    
    # 验证数据完整性
    if not user_id or status not in ('online', 'offline'):
        return

    # 更新服务器端的状态记录
    if status == 'online':
        mark_user_online(chat_user_sids, sid_chat_users, user_id)
        users_in_chat[user_id] = True
    elif status == 'offline':
        mark_user_offline(chat_user_sids, sid_chat_users, user_id)
        if not is_user_online(chat_user_sids, user_id) and user_id in users_in_chat:
            del users_in_chat[user_id]
    effective_status = 'online' if is_user_online(chat_user_sids, user_id) else 'offline'
            
    # 向对方广播状态更新
    other_user = User.query.filter(User.id != user_id).first()
    if other_user:
        room = f'user_{other_user.id}'
        socketio.emit('status_update', {'user_id': user_id, 'status': effective_status}, room=room)
        logger.info('向房间 %s 广播了用户 %s 的状态: %s', room, user_id, effective_status)
        
        # 新增：当用户上线时，立即将对方的状态告诉该用户，实现双向同步
        if effective_status == 'online':
            is_partner_online = is_user_online(chat_user_sids, other_user.id)
            current_user_room = f'user_{user_id}'
            socketio.emit('status_update', {
                'user_id': other_user.id, 
                'status': 'online' if is_partner_online else 'offline'
            }, room=current_user_room)
            logger.info('向房间 %s 发送了伙伴 %s 的状态: %s', current_user_room, other_user.id, 'online' if is_partner_online else 'offline')

# 新增：用户离开聊天页
@socketio.on('leave_chat')
def handle_leave_chat(data):
    user_id = normalize_user_id(data.get('user_id'))
    if not user_id:
        return
    mark_user_offline(chat_user_sids, sid_chat_users, user_id)
    should_notify_offline = not is_user_online(chat_user_sids, user_id)
    if user_id in users_in_chat and should_notify_offline:
        del users_in_chat[user_id]
    logger.info('用户 %s 主动离开了聊天页面', user_id)

    # 通知对方自己已下线
    other_user = User.query.filter(User.id != user_id).first()
    if other_user and should_notify_offline:
        socketio.emit('status_update', {'user_id': user_id, 'status': 'offline'}, room=f'user_{other_user.id}')

# 新增：花园状态更新处理器（完全仿照聊天的status_update逻辑，但独立管理）
@socketio.on('garden_status_update')
def handle_garden_status_update(data):
    user_id = normalize_user_id(data.get('user_id'))
    status = data.get('status')  # 'online' or 'offline'

    # 验证数据完整性
    if not user_id or status not in ('online', 'offline'):
        return

    # 更新服务器端的花园状态记录
    if status == 'online':
        mark_user_online(garden_user_sids, sid_garden_users, user_id)
        users_in_garden[user_id] = True
    elif status == 'offline':
        mark_user_offline(garden_user_sids, sid_garden_users, user_id)
        if not is_user_online(garden_user_sids, user_id) and user_id in users_in_garden:
            del users_in_garden[user_id]
    effective_status = 'online' if is_user_online(garden_user_sids, user_id) else 'offline'

    # 向对方广播花园状态更新
    other_user = User.query.filter(User.id != user_id).first()
    if other_user:
        room = f'user_{other_user.id}'
        socketio.emit('partner_garden_status', {'user_id': user_id, 'status': effective_status}, room=room)
        logger.info('向房间 %s 广播了用户 %s 的花园状态: %s', room, user_id, effective_status)

        # 当用户上线时，立即将对方的状态告诉该用户，实现双向同步
        if effective_status == 'online':
            is_partner_in_garden = is_user_online(garden_user_sids, other_user.id)
            current_user_room = f'user_{user_id}'
            socketio.emit('partner_garden_status', {
                'user_id': other_user.id,
                'status': 'online' if is_partner_in_garden else 'offline'
            }, room=current_user_room)
            logger.info('向房间 %s 发送了伙伴 %s 的花园状态: %s', current_user_room, other_user.id, 'online' if is_partner_in_garden else 'offline')

# 新增：心跳响应机制
@socketio.on('heartbeat')
def handle_heartbeat(data):
    """响应客户端的心跳请求，让客户端知道服务器是活的"""
    # print(f"收到来自 {data.get('user_id')} 的心跳")
    socketio.emit('heartbeat_response', {'timestamp': datetime.datetime.utcnow().isoformat()}, room=request.sid)

# 新增：处理新消息
@socketio.on('send_message')
def handle_send_message(data):
    """处理并广播新消息"""
    sender_id = normalize_user_id(data.get('sender_id'))
    content = data.get('content')
    message_type = data.get('message_type', 'text')

    if not all([sender_id, content]):
        return # 如果关键信息不全，则忽略

    # 1. 动态查找接收者ID
    other_user = User.query.filter(User.id != sender_id).first()
    if not other_user:
        return # 找不到接收者
    receiver_id = other_user.id

    # 2. 保存消息到数据库
    new_message = Message(
        sender_id=sender_id,
        receiver_id=receiver_id,
        content=content,
        message_type=message_type,
        is_read=is_user_online(chat_user_sids, receiver_id) # 如果接收者在聊天室，则标记为已读
    )
    db.session.add(new_message)
    db.session.commit()

    # 3. 准备要发送给前端的消息数据
    message_data = {
        'id': new_message.id,
        'content': new_message.content,
        'message_type': new_message.message_type,
        'timestamp': new_message.timestamp.isoformat(),
        'sender_id': new_message.sender_id,
        'receiver_id': new_message.receiver_id
    }

    # 4. 将消息实时发送给接收者和发送者本人
    sender_room = f'user_{sender_id}'
    receiver_room = f'user_{receiver_id}'
    socketio.emit('new_message', message_data, room=sender_room)
    socketio.emit('new_message', message_data, room=receiver_room)

    # 5. 如果接收者不在聊天页面，则发送全局通知
    if not is_user_online(chat_user_sids, receiver_id):
        sender = db.session.get(User, sender_id)
        if sender:
            notification = {
                'message': f'您收到了来自 {sender.role} 的一条新消息'
            }
            socketio.emit('global_new_message', notification, room=receiver_room)

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('客户端断开连接: %s', request.sid)
    # 处理用户意外断连（例如关闭浏览器）
    chat_user_id = sid_chat_users.pop(request.sid, None)
    garden_user_id = sid_garden_users.pop(request.sid, None)
    user_id = sid_to_user.pop(request.sid, None)

    if user_id:
        if chat_user_id:
            chat_user_sids.get(chat_user_id, set()).discard(request.sid)
            if chat_user_id in chat_user_sids and not chat_user_sids[chat_user_id]:
                del chat_user_sids[chat_user_id]

        if chat_user_id and not is_user_online(chat_user_sids, chat_user_id) and chat_user_id in users_in_chat:
            del users_in_chat[chat_user_id]

        if garden_user_id:
            garden_user_sids.get(garden_user_id, set()).discard(request.sid)
            if garden_user_id in garden_user_sids and not garden_user_sids[garden_user_id]:
                del garden_user_sids[garden_user_id]

        if garden_user_id and not is_user_online(garden_user_sids, garden_user_id) and garden_user_id in users_in_garden:
            del users_in_garden[garden_user_id]

        logger.info('用户 %s (SID: %s) 意外断开连接', user_id, request.sid)

        # 通知对方自己已下线
        other_user = User.query.filter(User.id != user_id).first()
        if other_user:
            if chat_user_id and not is_user_online(chat_user_sids, chat_user_id):
                socketio.emit('status_update', {'user_id': chat_user_id, 'status': 'offline'}, room=f'user_{other_user.id}')
            if garden_user_id and not is_user_online(garden_user_sids, garden_user_id):
                socketio.emit('partner_garden_status', {'user_id': garden_user_id, 'status': 'offline'}, room=f'user_{other_user.id}')

if __name__ == '__main__':
    # 必须使用socketio.run来启动，这样才能同时支持HTTP和WebSocket
    # 监听所有网络接口，这样移动设备才能直接连接
    socketio.run(app, host='0.0.0.0', port=5000, debug=app.config['DEBUG']) 
