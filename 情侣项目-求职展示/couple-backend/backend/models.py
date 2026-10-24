from backend.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pytz

def get_beijing_time():
    """获取北京时间"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.datetime.now(beijing_tz).replace(tzinfo=None)

class User(db.Model):
    """用户模型"""
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 例如: "男朋友", "女朋友"
    # 存储当前有效的JWT的JTI (JWT ID), 用于实现单设备登录
    current_jti = db.Column(db.String(36), nullable=True) 
    # 新增：存储最后一次登录的设备ID，用于区分同一设备的多次登录
    device_id = db.Column(db.String(36), nullable=True)
    # 新增：存储用户头像的URL
    avatar = db.Column(db.String(200), nullable=True)

    def set_password(self, password):
        """设置密码"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """校验密码"""
        return check_password_hash(self.password_hash, password)

class Diary(db.Model):
    """日记模型"""
    __tablename__ = 'diary'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(200), nullable=True)
    weather = db.Column(db.String(50), nullable=True)
    tags = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, index=True, default=get_beijing_time)
    
    # 外键，关联到用户的主键
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # 关系字段，方便从日记对象直接访问作者信息
    author = db.relationship('User', backref=db.backref('diaries', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_diary_user_timestamp', 'user_id', 'timestamp'),
    )

    def __repr__(self):
        return f'<Diary {self.title}>'

class Message(db.Model):
    """聊天消息模型"""
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=get_beijing_time)
    
    # 消息类型: 'text' 或 'image'
    message_type = db.Column(db.String(20), nullable=False, default='text')
    
    # 消息是否已被读取
    is_read = db.Column(db.Boolean, default=False)
    
    # 外键，关联到发送者和接收者
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # 关系字段，方便从消息对象直接访问作者和接收者信息
    # foreign_keys 指定了用于建立关系的具体外键列
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')

    __table_args__ = (
        db.Index('ix_message_sender_receiver_id', 'sender_id', 'receiver_id', 'id'),
        db.Index('ix_message_receiver_sender_id', 'receiver_id', 'sender_id', 'id'),
        db.Index('ix_message_receiver_read', 'receiver_id', 'is_read'),
    )

    def __repr__(self):
        return f'<Message {self.id} from {self.sender_id} to {self.receiver_id}>'

class LoveGarden(db.Model):
    """爱情花园模型 - 全局唯一，两个用户共享"""
    __tablename__ = 'love_garden'
    id = db.Column(db.Integer, primary_key=True)

    # 成长核心数值
    level = db.Column(db.Integer, default=1, nullable=False)
    experience = db.Column(db.Integer, default=0, nullable=False)

    # 五大核心数值 (根据设计文档设定初始值和范围)
    health = db.Column(db.Float, default=10.0, nullable=False)      # 健康度: 初始10, 最大100
    care = db.Column(db.Float, default=0.0, nullable=False)         # 关怀值: 初始0, 最大100
    companion = db.Column(db.Float, default=0.0, nullable=False)    # 陪伴值: 初始0, 最大100
    love = db.Column(db.Float, default=0.0, nullable=False)         # 爱心值: 初始0, 最大100
    sweetness = db.Column(db.Float, default=0.0, nullable=False)    # 甜蜜值: 初始0, 最大100

    # 记录上一次数值更新的时间 (用于每日衰减计算)
    last_updated = db.Column(db.DateTime, default=get_beijing_time, nullable=False)

    # 花园创建时间
    created_at = db.Column(db.DateTime, default=get_beijing_time, nullable=False)

    def __repr__(self):
        return f'<LoveGarden Level {self.level} - XP {self.experience}>'

class GardenAction(db.Model):
    """花园每日操作记录模型 - 简化版本"""
    __tablename__ = 'garden_action'
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # 操作类型: water(浇水), fertilize(施肥), weed(除草), wish(许愿), photo(合影)
    action_type = db.Column(db.String(20), nullable=False)

    # 操作发生的日期 (只记录日期，不记录具体时间)
    action_date = db.Column(db.Date, nullable=False)

    # 操作时间戳 (用于判断是否同时在线)
    action_time = db.Column(db.DateTime, default=get_beijing_time, nullable=False)

    # 建立用户关系
    user = db.relationship('User', backref=db.backref('garden_actions', lazy='dynamic'))

    # 确保每个用户每天每种操作只能执行一次
    __table_args__ = (
        db.UniqueConstraint('user_id', 'action_type', 'action_date',
                          name='_user_action_date_unique'),
        db.Index('ix_garden_action_user_date', 'user_id', 'action_date'),
        db.Index('ix_garden_action_date_type', 'action_date', 'action_type'),
    )

    def __repr__(self):
        return f'<GardenAction {self.user_id} did {self.action_type} on {self.action_date}>'


class Music(db.Model):
    """音乐盒音乐模型"""
    __tablename__ = 'music'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)  # 存储上传后的文件名
    duration = db.Column(db.Integer, nullable=False)  # 存储音频时长，单位为秒
    timestamp = db.Column(db.DateTime, index=True, default=get_beijing_time)

    # 外键，关联到用户的主键
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # 关系字段，方便从音乐对象直接访问作者信息
    author = db.relationship('User', backref=db.backref('musics', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_music_user_timestamp', 'user_id', 'timestamp'),
    )

    def __repr__(self):
        return f'<Music {self.title}>'
