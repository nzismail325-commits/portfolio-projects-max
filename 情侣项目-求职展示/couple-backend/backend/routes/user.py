import logging
import os

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from backend.auth_utils import get_current_user_id
from backend.extensions import socketio
from backend.models import User, db
from backend.utils.image_processing import is_allowed_image, save_optimized_avatar


user_bp = Blueprint('user', __name__)
logger = logging.getLogger(__name__)


@user_bp.route('/avatar', methods=['POST'])
@jwt_required()
def upload_avatar():
    current_user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"msg": "请求中没有文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"msg": "没有选择文件"}), 400

    if not is_allowed_image(file.filename):
        return jsonify({"msg": "不允许的文件类型"}), 400

    user = db.session.get(User, current_user_id)
    if not user:
        return jsonify({"msg": "未找到用户"}), 404

    upload_folder = current_app.config['AVATAR_UPLOAD_FOLDER']

    try:
        filename, _ = save_optimized_avatar(file, upload_folder)
    except Exception as exc:
        logger.warning("Avatar upload processing failed: %s", exc)
        return jsonify({"msg": "头像处理失败，请换一张图片重试"}), 400

    if user.avatar and 'placehold.co' not in user.avatar:
        try:
            old_avatar_filename = user.avatar.split('/')[-1]
            old_avatar_path = os.path.join(upload_folder, old_avatar_filename)
            if os.path.exists(old_avatar_path):
                os.remove(old_avatar_path)
        except Exception as exc:
            logger.warning("Failed to delete old avatar: %s", exc)

    file_url = f'/uploads/avatars/{filename}'
    user.avatar = file_url
    db.session.commit()

    avatar_update_data = {
        'user_id': current_user_id,
        'avatar_url': file_url
    }

    socketio.emit('avatar_updated', avatar_update_data, room=f'user_{current_user_id}')

    other_user = User.query.filter(User.id != current_user_id).first()
    if other_user:
        socketio.emit('avatar_updated', avatar_update_data, room=f'user_{other_user.id}')

    return jsonify({'url': file_url}), 201
