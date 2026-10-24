from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
from backend.auth_utils import get_current_user_id
from backend.extensions import db, socketio
from backend.models import Music, User
import os
import logging
from werkzeug.utils import secure_filename
import uuid

logger = logging.getLogger(__name__)

# 在导入 pydub 之前先设置 ffmpeg 路径
# 当前文件是 backend/routes/music.py，需要向上回退三层到达项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ffmpeg_path = os.path.join(project_root, 'ffmpeg-2025-04-23-git-25b0a8e295-essentials_build', 'bin', 'ffmpeg.exe')
ffprobe_path = os.path.join(project_root, 'ffmpeg-2025-04-23-git-25b0a8e295-essentials_build', 'bin', 'ffprobe.exe')

logger.debug("当前文件: %s", __file__)
logger.debug("项目根目录: %s", project_root)
logger.debug("FFmpeg路径: %s", ffmpeg_path)
logger.debug("FFprobe路径: %s", ffprobe_path)
logger.debug("FFmpeg存在: %s", os.path.exists(ffmpeg_path))
logger.debug("FFprobe存在: %s", os.path.exists(ffprobe_path))

# 设置环境变量，让 pydub 能找到 ffmpeg
os.environ['PATH'] = os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get('PATH', '')

# 现在导入 pydub
from pydub import AudioSegment
from pydub.utils import which
from pydub.exceptions import CouldntDecodeError

# 双重保险：同时设置 AudioSegment 的属性
AudioSegment.converter = ffmpeg_path
AudioSegment.ffprobe = ffprobe_path

logger.debug("pydub找到的ffmpeg: %s", which('ffmpeg'))
logger.debug("pydub找到的ffprobe: %s", which('ffprobe'))

music_bp = Blueprint('music', __name__)

# 允许的音频文件扩展名 - 扩展支持手机录音格式
ALLOWED_EXTENSIONS = {
    'mp3', 'wav', 'flac',  # 原有格式
    'm4a', 'aac', '3gp', 'amr', 'ogg', 'webm', 'opus' # 新增手机常用格式
}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_to_mp3(filepath, original_ext):
    """
    将音频文件转换为MP3格式。
    返回新的文件名和文件路径，如果转换失败则返回None。
    """
    # 关键修复：如果文件本身就是 MP3，则不进行转换，直接返回原路径和文件名
    if original_ext.lower() == '.mp3':
        logger.info("文件已经是MP3格式，跳过转码: %s", filepath)
        return os.path.basename(filepath), filepath
        
    try:
        logger.info("开始转码: %s", filepath)
        # 使用原始扩展名加载，因为pydub可能需要它来正确解码
        audio = AudioSegment.from_file(filepath, format=original_ext.replace('.', ''))
        
        # 定义新的MP3文件名和路径
        base_path = os.path.splitext(filepath)[0]
        new_filepath = f"{base_path}.mp3"
        new_filename = os.path.basename(new_filepath)
        
        # 导出为MP3
        # 使用192kbps码率，这是一个音质和文件大小的良好平衡点
        audio.export(new_filepath, format="mp3", bitrate="192k")
        
        logger.info("转码成功: %s", new_filepath)
        logger.debug("返回的文件名: %s", new_filename)
        logger.debug("文件是否存在: %s", os.path.exists(new_filepath))
        
        # 删除原始文件
        try:
            os.remove(filepath)
            logger.info("已删除原始文件: %s", filepath)
        except OSError as e:
            logger.warning("删除原始文件失败: %s", e)
            
        return new_filename, new_filepath
        
    except CouldntDecodeError:
        logger.warning("解码失败: %s。文件可能已损坏或格式不受ffmpeg支持。", filepath)
        return None, None
    except Exception as e:
        logger.exception("转码时发生未知错误: %s", e)
        return None, None


@music_bp.route('/', methods=['GET'])
@jwt_required()
def get_all_music():
    """获取所有音乐列表"""
    try:
        limit = request.args.get('limit', type=int)
        page = request.args.get('page', type=int)
        page_size = request.args.get('page_size', type=int)
        query = Music.query.order_by(Music.timestamp.desc())

        if page or page_size:
            page = max(page or 1, 1)
            page_size = min(max(page_size or limit or 50, 1), 100)
            musics = query.limit(page_size).offset((page - 1) * page_size).all()
        elif limit:
            musics = query.limit(min(max(limit, 1), 100)).all()
        else:
            musics = query.all()
        music_list = []
        for music in musics:
            # 确保author存在并且有有效的用户名
            author_info = None
            if music.author and music.author.username:
                author_info = {
                    'id': music.author.id,
                    'name': music.author.username,
                    'avatar': music.author.avatar
                }
            else:
                # 如果author不存在或username为空，提供默认信息
                author_info = {
                    'id': None,
                    'name': '未知用户',
                    'avatar': None
                }
            
            music_list.append({
                'id': music.id,
                'title': music.title or '未知标题',
                'url': f'/uploads/music/{music.filename}',
                'duration': music.duration or 0,
                'timestamp': music.timestamp.isoformat() if music.timestamp else '',
                'author': author_info
            })
        
        return jsonify(music_list), 200
        
    except Exception as e:
        logger.exception("获取音乐列表失败: %s", e)
        return jsonify({'error': '获取音乐列表失败'}), 500

@music_bp.route('/', methods=['POST'])
@jwt_required()
def upload_music():
    """上传一首新音乐并转码为MP3"""
    try:
        current_user_id = get_current_user_id()
        
        # 检查文件是否存在
        if 'file' not in request.files:
            return jsonify({"msg": "请选择要上传的音频文件", "error_code": "NO_FILE"}), 400
        
        file = request.files['file']
        title = request.form.get('title')
        duration = request.form.get('duration', type=int, default=0) # 直接从表单获取时长

        # 检查标题
        if not title or title.strip() == '':
            return jsonify({"msg": "请输入歌曲标题", "error_code": "NO_TITLE"}), 400
        
        # 检查文件名
        if file.filename == '':
            return jsonify({"msg": "请选择有效的音频文件", "error_code": "EMPTY_FILENAME"}), 400

        # 检查文件格式
        if not file or not allowed_file(file.filename):
            file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else '无扩展名'
            supported_formats = ', '.join(ALLOWED_EXTENSIONS)
            return jsonify({
                "msg": f"不支持的文件格式: {file_ext}。支持的格式: {supported_formats}", 
                "error_code": "UNSUPPORTED_FORMAT",
                "file_extension": file_ext,
                "supported_formats": list(ALLOWED_EXTENSIONS)
            }), 400

        # 检查文件大小（限制为50MB）
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()
        file.seek(0)  # 重置文件指针
        max_size = 50 * 1024 * 1024  # 50MB
        
        if file_size > max_size:
            return jsonify({
                "msg": f"文件过大。当前大小: {file_size // (1024*1024)}MB，最大允许: {max_size // (1024*1024)}MB",
                "error_code": "FILE_TOO_LARGE",
                "file_size": file_size,
                "max_size": max_size
            }), 400

        # 先保存原始文件
        original_ext = os.path.splitext(file.filename)[1]
        # 创建一个临时的、唯一的安全文件名来保存原始文件
        temp_filename = f"{current_user_id}_{secure_filename(title)}_{uuid.uuid4().hex}{original_ext}"
        upload_folder = current_app.config['UPLOAD_FOLDER_MUSIC']
        
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        original_filepath = os.path.join(upload_folder, temp_filename)
        file.save(original_filepath)
        
        # 转码为MP3
        final_filename, final_filepath = convert_to_mp3(original_filepath, original_ext)
        if not final_filename:
            # 如果转码失败，清理临时文件并返回错误
            try:
                os.remove(original_filepath)
            except OSError:
                pass
            return jsonify({"msg": "音频文件解码或转码失败，请尝试其他文件或格式。"}), 400

        # 保存到数据库
        try:
            new_music = Music(
                title=title.strip(),
                filename=final_filename, # 保存MP3文件名
                duration=duration,
                user_id=current_user_id
            )
            db.session.add(new_music)
            db.session.commit()
        except Exception as e:
            # 如果数据库保存失败，删除已保存的文件
            try:
                os.remove(final_filepath) # 删除转码后的MP3文件
            except:
                pass
            return jsonify({
                "msg": f"数据库保存失败: {str(e)}", 
                "error_code": "DB_SAVE_FAILED"
            }), 500

        # 广播音乐列表更新事件
        socketio.emit('music_updated')
        logger.info("已广播 'music_updated' 事件 (上传)")

        # 返回新创建的音乐数据
        response = {
            'id': new_music.id,
            'title': new_music.title,
            'url': f'/uploads/music/{new_music.filename}',
            'duration': new_music.duration,
            'timestamp': new_music.timestamp.isoformat(),
            'author': {
                'id': new_music.author.id,
                'name': new_music.author.username,
                'avatar': new_music.author.avatar
            }
        }
        
        logger.debug("返回给前端的URL: %s", response['url'])
        logger.debug("实际文件路径: %s", final_filepath)
        
        return jsonify(response), 201

    except Exception as e:
        logger.exception("上传音乐失败: %s", e)
        return jsonify({
            "msg": f"上传失败: {str(e)}", 
            "error_code": "GENERAL_ERROR"
        }), 500


@music_bp.route('/<int:music_id>', methods=['DELETE'])
@jwt_required()
def delete_music(music_id):
    """删除一首音乐"""
    current_user_id = get_current_user_id()
    music = Music.query.get(music_id)

    if not music:
        return jsonify({"msg": "Music not found"}), 404

    if music.user_id != current_user_id:
        return jsonify({"msg": "Unauthorized"}), 403

    try:
        # 从文件系统删除文件
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER_MUSIC'], music.filename)
        if os.path.exists(filepath):
            os.remove(filepath)

        # 从数据库删除记录
        db.session.delete(music)
        db.session.commit()

        # 广播音乐列表更新事件
        socketio.emit('music_updated')
        logger.info("已广播 'music_updated' 事件 (删除)")

        return jsonify({"msg": "Music deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Failed to delete music", "error": str(e)}), 500 
