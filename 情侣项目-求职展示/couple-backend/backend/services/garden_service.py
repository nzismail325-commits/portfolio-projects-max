"""
爱情花园业务逻辑服务
实现核心的花园养成逻辑，包括数值计算、等级升级、每日衰减、惩罚机制等
"""

from datetime import datetime, date, timedelta
from sqlalchemy import and_
from backend.models import User, LoveGarden, GardenAction, get_beijing_time
from backend.extensions import db
import logging

logger = logging.getLogger(__name__)

class GardenService:
    """爱情花园服务类"""
    
    # 等级经验阈值 (按设计文档)
    LEVEL_THRESHOLDS = {
        1: 0,
        2: 2500,
        3: 4500,
        4: 6600,
        5: 8000
    }
    
    # 操作基础数值收益 (根据设计文档)
    ACTION_BASE_VALUES = {
        'water': {'health': 1.6, 'experience': 6},
        'fertilize': {'care': 1.4, 'experience': 6},
        'weed': {'companion': 1.4, 'experience': 6},
        'wish': {'love': 1.8, 'experience': 6},
        'photo': {'sweetness': 1.8, 'experience': 6}
    }
    
    # 每日衰减值
    DAILY_DECAY = 1.0
    
    # 同时在线判定时间窗口 (秒)
    ONLINE_TIME_WINDOW = 300  # 5分钟
    
    @staticmethod
    def get_or_create_garden():
        """获取或创建唯一的爱情花园"""
        garden = LoveGarden.query.first()
        if not garden:
            garden = LoveGarden()
            db.session.add(garden)
            db.session.commit()
            logger.info("创建了新的爱情花园")
        return garden
    
    @staticmethod
    def calculate_health_multiplier(health):
        """根据健康度计算经验倍率"""
        if health < 20:
            return 0.5  # 生病状态
        elif health < 40:
            return 0.8  # 不佳状态
        else:
            return 1.0  # 健康状态
    
    @staticmethod
    def check_both_users_online_in_garden():
        """
        检查双方是否都在花园页面在线
        Returns:
            bool: 双方是否都在线
        """
        from backend.app import users_in_garden
        from backend.models import User

        # 获取所有用户
        users = User.query.all()
        if len(users) < 2:
            logger.info(f"用户数量不足2个: {len(users)}")
            return False

        # 检查双方是否都在花园在线
        user1_online = users_in_garden.get(users[0].id, False)
        user2_online = users_in_garden.get(users[1].id, False)

        logger.info(f"花园在线状态检查: 用户{users[0].id}={user1_online}, 用户{users[1].id}={user2_online}, 当前users_in_garden={users_in_garden}")

        return user1_online and user2_online
    
    @staticmethod
    def calculate_level_from_experience(experience):
        """根据经验值计算等级"""
        for level in range(5, 0, -1):
            if experience >= GardenService.LEVEL_THRESHOLDS[level]:
                return level
        return 1
    
    @staticmethod
    def get_next_level_exp(current_level):
        """获取下一级所需经验"""
        if current_level >= 5:
            return GardenService.LEVEL_THRESHOLDS[5]
        return GardenService.LEVEL_THRESHOLDS[current_level + 1]
    
    @staticmethod
    def get_today_actions(user_id, target_date=None):
        """
        获取用户指定日期的操作记录
        Args:
            user_id: 用户ID
            target_date: 目标日期，默认为今天
        Returns:
            dict: 操作记录字典
        """
        if target_date is None:
            target_date = date.today()
            
        actions = GardenAction.query.filter(
            and_(
                GardenAction.user_id == user_id,
                GardenAction.action_date == target_date
            )
        ).all()
        
        action_dict = {}
        for action in actions:
            action_dict[action.action_type] = {
                'completed': True,
                'time': action.action_time
            }
        
        return action_dict
    
    @staticmethod
    def can_perform_action(user_id, action_type, target_date=None):
        """
        检查用户是否可以执行指定操作
        Args:
            user_id: 用户ID
            action_type: 操作类型
            target_date: 目标日期，默认为今天
        Returns:
            bool: 是否可以执行
        """
        if target_date is None:
            target_date = date.today()
            
        existing_action = GardenAction.query.filter(
            and_(
                GardenAction.user_id == user_id,
                GardenAction.action_type == action_type,
                GardenAction.action_date == target_date
            )
        ).first()
        
        return existing_action is None
    
    @staticmethod
    def perform_action(user_id, action_type, has_online_bonus=False):
        """
        执行花园操作
        Args:
            user_id: 用户ID
            action_type: 操作类型
            has_online_bonus: 是否有在线加成（由前端传入）
        Returns:
            dict: 操作结果
        """
        if action_type not in GardenService.ACTION_BASE_VALUES:
            return {'success': False, 'message': '无效的操作类型'}
        
        # 检查今日是否已经执行过该操作
        if not GardenService.can_perform_action(user_id, action_type):
            return {'success': False, 'message': '今日已经执行过该操作'}
        
        # 获取花园数据
        garden = GardenService.get_or_create_garden()
        
        # 记录操作
        action_time = get_beijing_time()
        today = date.today()
        new_action = GardenAction(
            user_id=user_id,
            action_type=action_type,
            action_date=today,
            action_time=action_time
        )
        db.session.add(new_action)
        
        # 获取对方用户信息
        other_user = User.query.filter(User.id != user_id).first()

        # 计算数值和经验增长
        base_values = GardenService.ACTION_BASE_VALUES[action_type]

        # 根据前端传入的在线状态计算加成倍率（简化逻辑）
        # 数值收益：同时在线时1.5倍，否则1.0倍
        online_multiplier_value = 1.5 if has_online_bonus else 1.0
        # 经验收益：同时在线时2.0倍，否则1.0倍
        online_multiplier_exp = 2.0 if has_online_bonus else 1.0
        
        # 计算健康度倍率
        health_multiplier = GardenService.calculate_health_multiplier(garden.health)
        
        # 记录旧等级
        old_level = garden.level
        
        # 应用数值增长
        for stat, value in base_values.items():
            if stat == 'experience':
                # 经验计算: 基础经验 * 健康度倍率 * 在线倍率
                exp_gain = value * health_multiplier * online_multiplier_exp
                garden.experience += int(exp_gain)
            else:
                # 数值计算: 基础数值 * 在线倍率，限制在100以内
                stat_gain = value * online_multiplier_value
                current_value = getattr(garden, stat)
                setattr(garden, stat, min(100.0, current_value + stat_gain))
        
        # 检查等级升级
        new_level = GardenService.calculate_level_from_experience(garden.experience)
        garden.level = new_level
        
        # 更新最后更新时间
        garden.last_updated = action_time
        
        db.session.commit()
        
        logger.info(f"用户 {user_id} 执行了 {action_type} 操作，在线加成: {has_online_bonus}, 数值倍率: {online_multiplier_value}, 经验倍率: {online_multiplier_exp}")

        return {
            'success': True,
            'message': '操作成功！',
            'garden': garden,
            'level_up': new_level > old_level,
            'online_bonus': has_online_bonus,  # 返回前端传入的加成状态
            'other_user': other_user
        }
    
    @staticmethod
    def apply_daily_settlement(target_date=None):
        """
        应用每日结算
        Args:
            target_date: 结算日期，默认为昨天
        Returns:
            dict: 结算结果
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        
        garden = GardenService.get_or_create_garden()
        
        # 获取所有用户
        users = User.query.all()
        user_ids = [user.id for user in users]
        
        # 处理每种操作类型的惩罚
        total_penalty_exp = 0
        penalty_details = {}
        
        for action_type, base_values in GardenService.ACTION_BASE_VALUES.items():
            # 获取指定日期该操作的执行情况
            actions_on_date = GardenAction.query.filter(
                and_(
                    GardenAction.action_type == action_type,
                    GardenAction.action_date == target_date
                )
            ).all()
            
            performed_users = [action.user_id for action in actions_on_date]
            missing_users = [uid for uid in user_ids if uid not in performed_users]
            
            if len(missing_users) == len(user_ids):
                # 双方都未操作 - 应用双方缺席惩罚
                for stat, value in base_values.items():
                    if stat == 'experience':
                        penalty_exp = value * 3  # 3倍经验惩罚
                        total_penalty_exp += penalty_exp
                    else:
                        penalty_value = value * 2.5  # 2.5倍数值惩罚
                        current_value = getattr(garden, stat)
                        # 健康值有最低10点保护，其他数值最低为0
                        min_value = 10.0 if stat == 'health' else 0.0
                        setattr(garden, stat, max(min_value, current_value - penalty_value))
                penalty_details[action_type] = 'both_missing'
                
            elif len(missing_users) > 0:
                # 单方缺席惩罚
                for stat, value in base_values.items():
                    if stat == 'experience':
                        penalty_exp = value * 2  # 2倍经验惩罚
                        total_penalty_exp += penalty_exp
                    else:
                        penalty_value = value * 2  # 2倍数值惩罚
                        current_value = getattr(garden, stat)
                        # 健康值有最低10点保护，其他数值最低为0
                        min_value = 10.0 if stat == 'health' else 0.0
                        setattr(garden, stat, max(min_value, current_value - penalty_value))
                penalty_details[action_type] = 'single_missing'
        
        # 应用经验惩罚
        garden.experience = max(0, garden.experience - total_penalty_exp)
        
        # 应用每日衰减（健康值有最低10点保护，其他数值最低为0）
        garden.health = max(10.0, garden.health - GardenService.DAILY_DECAY)
        garden.care = max(0.0, garden.care - GardenService.DAILY_DECAY)
        garden.companion = max(0.0, garden.companion - GardenService.DAILY_DECAY)
        garden.love = max(0.0, garden.love - GardenService.DAILY_DECAY)
        garden.sweetness = max(0.0, garden.sweetness - GardenService.DAILY_DECAY)
        
        # 重新计算等级
        garden.level = GardenService.calculate_level_from_experience(garden.experience)
        garden.last_updated = get_beijing_time()
        
        db.session.commit()
        
        logger.info(f"完成每日结算，日期: {target_date}，经验惩罚: {total_penalty_exp}")
        
        return {
            'success': True,
            'penalty_details': penalty_details,
            'total_penalty_exp': total_penalty_exp,
            'garden': garden
        }
