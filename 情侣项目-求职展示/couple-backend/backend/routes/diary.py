from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from backend.auth_utils import get_current_user_id
from backend.models import db, User, Diary
from backend.extensions import socketio
from datetime import datetime, timedelta

# 创建一个新的蓝图对象
diary_bp = Blueprint('diary', __name__)

def diary_to_dict(diary):
    """将Diary对象序列化为字典"""
    return {
        'id': diary.id,
        'title': diary.title,
        'content': diary.content,
        'excerpt': diary.excerpt,
        'weather': diary.weather,
        'tags': diary.tags.split(',') if diary.tags else [],
        'timestamp': diary.timestamp.isoformat(),
        'author': {
            'id': diary.author.id,
            'username': diary.author.username,
            'role': diary.author.role,
            'avatar': diary.author.avatar
        }
    }

@diary_bp.route('/diaries', methods=['GET'])
@jwt_required()
def get_diaries():
    """获取所有日记，支持搜索和日期筛选"""
    query = Diary.query

    # 1. 关键词搜索 (q)
    search_term = request.args.get('q')
    if search_term:
        query = query.filter(or_(
            Diary.title.ilike(f'%{search_term}%'),
            Diary.content.ilike(f'%{search_term}%')
        ))

    # 2. 日期筛选 (year, month, day)
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        day = request.args.get('day', type=int)
    except (ValueError, TypeError):
        return jsonify({"msg": "日期参数格式不正确"}), 400

    if year:
        start_month = month or 1
        start_day = day or 1
        try:
            start_time = datetime(year, start_month, start_day)
            if day:
                end_time = start_time + timedelta(days=1)
            elif month:
                end_time = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
            else:
                end_time = datetime(year + 1, 1, 1)
        except ValueError:
            return jsonify({"msg": "日期参数范围不正确"}), 400
        query = query.filter(Diary.timestamp >= start_time, Diary.timestamp < end_time)

    page = request.args.get('page', type=int)
    page_size = request.args.get('page_size', type=int)
    query = query.order_by(Diary.timestamp.desc())

    if page or page_size:
        page = max(page or 1, 1)
        page_size = min(max(page_size or 20, 1), 100)
        pagination = query.paginate(page=page, per_page=page_size, error_out=False)
        return jsonify({
            'items': [diary_to_dict(d) for d in pagination.items],
            'total': pagination.total,
            'page': page,
            'page_size': page_size,
            'has_next': pagination.has_next
        }), 200

    diaries = query.all()
    return jsonify([diary_to_dict(d) for d in diaries]), 200

@diary_bp.route('/diaries', methods=['POST'])
@jwt_required()
def create_diary():
    """创建新日记"""
    data = request.get_json()
    current_user_id = get_current_user_id()
    
    # 从前端数据创建日记对象
    new_diary = Diary(
        title=data.get('title'),
        content=data.get('content'),
        excerpt=data.get('excerpt'),
        weather=data.get('weather'),
        tags=','.join(data.get('tags', [])),
        user_id=current_user_id
    )
    
    db.session.add(new_diary)
    db.session.commit()
    
    # 通过WebSocket广播新日记事件
    socketio.emit('new_diary', diary_to_dict(new_diary))
    
    return jsonify(diary_to_dict(new_diary)), 201

@diary_bp.route('/diaries/<int:diary_id>', methods=['PUT'])
@jwt_required()
def update_diary(diary_id):
    """更新日记"""
    current_user_id = get_current_user_id()
    diary = db.session.get(Diary, diary_id)
    
    if diary is None:
        return jsonify({"msg": "未找到该日记"}), 404
        
    # 验证是否为作者本人
    if diary.user_id != current_user_id:
        return jsonify({"msg": "权限不足，您不是该日记的作者"}), 403
        
    data = request.get_json()
    diary.title = data.get('title', diary.title)
    diary.content = data.get('content', diary.content)
    diary.excerpt = data.get('excerpt', diary.excerpt)
    diary.weather = data.get('weather', diary.weather)
    diary.tags = ','.join(data.get('tags', [])) if data.get('tags') is not None else diary.tags
    
    db.session.commit()
    
    # 通过WebSocket广播更新事件
    socketio.emit('updated_diary', diary_to_dict(diary))
    
    return jsonify(diary_to_dict(diary)), 200

@diary_bp.route('/diaries/<int:diary_id>', methods=['DELETE'])
@jwt_required()
def delete_diary(diary_id):
    """删除日记"""
    current_user_id = get_current_user_id()
    diary = db.session.get(Diary, diary_id)
    
    if diary is None:
        return jsonify({"msg": "未找到该日记"}), 404
        
    # 验证是否为作者本人
    if diary.user_id != current_user_id:
        return jsonify({"msg": "权限不足，您不是该日记的作者"}), 403
        
    db.session.delete(diary)
    db.session.commit()
    
    # 通过WebSocket广播删除事件
    # 我们只发送被删除日记的ID，前端根据ID进行移除
    socketio.emit('deleted_diary', {'id': diary_id})
    
    return jsonify({"msg": "日记已成功删除"}), 200 
