from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from backend.auth_utils import get_current_user_id
from backend.models import db, User, Message
from datetime import datetime, time, timedelta
import logging

chat_bp = Blueprint('chat', __name__)
logger = logging.getLogger(__name__)

def message_to_dict(message):
    """将Message对象序列化为字典"""
    return {
        'id': message.id,
        'content': message.content,
        'message_type': message.message_type,
        'timestamp': message.timestamp.isoformat(),
        'sender_id': message.sender_id,
        'receiver_id': message.receiver_id,
        'is_read': message.is_read
    }

@chat_bp.route('/messages', methods=['GET'])
@jwt_required()
def get_messages():
    """获取两位用户之间的聊天记录，支持分页或按日期查询"""
    current_user_id = get_current_user_id()
    
    # 获取查询参数
    before_id = request.args.get('before_id', type=int)
    after_id = request.args.get('after_id', type=int)
    limit = min(request.args.get('limit', 10, type=int), 100)
    query_date_str = request.args.get('date') # 获取日期参数
    
    # 查找另一个用户
    # 在这个应用中，用户只有两个，所以不是当前用户的就是另一个
    other_user = User.query.filter(User.id != current_user_id).first()
    if not other_user:
        return jsonify({"msg": "找不到对话的另一方"}), 404
    other_user_id = other_user.id
    
    # 构建基本查询
    query = Message.query.filter(
        or_(
            (Message.sender_id == current_user_id) & (Message.receiver_id == other_user_id),
            (Message.sender_id == other_user_id) & (Message.receiver_id == current_user_id)
        )
    )
    
    # 如果提供了日期，则按日期查询
    if query_date_str:
        try:
            # 解析日期字符串为日期对象
            query_date = datetime.strptime(query_date_str, '%Y-%m-%d').date()
            
            # 计算当天开始和结束的时间点
            start_of_day = datetime.combine(query_date, time(0, 0, 0))
            end_of_day = start_of_day + timedelta(days=1)
            
            logger.debug("查询日期: %s, 开始时间: %s, 结束时间: %s", query_date_str, start_of_day, end_of_day)
            
            # 使用严格的时间范围查询，确保不会包含下一天的消息
            query = query.filter(
                Message.timestamp >= start_of_day,
                Message.timestamp < end_of_day
            )

            if before_id:
                query = query.filter(Message.id < before_id)
            if after_id:
                query = query.filter(Message.id > after_id)
            
            messages = query.order_by(Message.id.asc()).limit(limit).all()
            
            logger.debug("找到 %s 条消息", len(messages))
                
        except ValueError as e:
            logger.error("日期解析错误: %s", str(e))
            return jsonify({"msg": "日期格式错误，请使用 YYYY-MM-DD 格式"}), 400
    # 否则，使用原有的分页逻辑
    else:
        # 如果提供了before_id，则获取该消息之前的消息
        if before_id:
            query = query.filter(Message.id < before_id)
        
        # 如果提供了after_id，则获取该消息之后的消息
        if after_id:
            query = query.filter(Message.id > after_id)
            # 对于after_id查询，按ID升序排序，获取最旧的limit条消息
            messages = query.order_by(Message.id.asc()).limit(limit).all()
        else:
            # 按时间戳降序排序，获取最新的limit条消息
            messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
            # 再按时间戳升序排序，确保消息按正确顺序返回
            messages.reverse()
    
    message_ids = [message.id for message in messages]
    if message_ids:
        Message.query.filter(
            Message.id.in_(message_ids),
            Message.receiver_id == current_user_id,
            Message.is_read.is_(False)
        ).update({Message.is_read: True}, synchronize_session=False)
        db.session.commit()
    
    return jsonify([message_to_dict(m) for m in messages]), 200 
