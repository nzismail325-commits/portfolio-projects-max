import logging

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from backend.utils.image_processing import is_allowed_image, save_optimized_image


upload_bp = Blueprint('upload', __name__)
logger = logging.getLogger(__name__)


@upload_bp.route('/image', methods=['POST'])
@jwt_required()
def upload_image():
    if 'file' not in request.files:
        return jsonify({"msg": "请求中没有文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"msg": "没有选择文件"}), 400

    if not is_allowed_image(file.filename):
        return jsonify({"msg": "不允许的文件类型"}), 400

    try:
        filename, _ = save_optimized_image(
            file,
            current_app.config['UPLOAD_FOLDER'],
            max_size=current_app.config.get('CHAT_IMAGE_MAX_SIZE', (1280, 1280)),
            quality=current_app.config.get('CHAT_IMAGE_QUALITY', 78),
        )
    except Exception as exc:
        logger.warning("Image upload processing failed: %s", exc)
        return jsonify({"msg": "图片处理失败，请换一张图片重试"}), 400

    return jsonify({'url': f'/uploads/chat_images/{filename}'}), 201
