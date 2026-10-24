from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from datetime import datetime, date, timedelta
from backend.auth_utils import get_current_user_id
from backend.models import User
from backend.extensions import db, socketio
from backend.services.garden_service import GardenService
from backend.services.garden_scheduler import manual_daily_settlement

# 创建花园蓝图
garden_bp = Blueprint('garden', __name__)

@garden_bp.route('/data', methods=['GET'])
@jwt_required()
def get_garden_data():
    """获取花园数据和今日操作状态"""
    current_user_id = get_current_user_id()

    # 获取花园数据
    garden = GardenService.get_or_create_garden()

    # 获取今日操作状态
    today_actions = GardenService.get_today_actions(current_user_id)

    # 获取对方用户信息
    other_user = User.query.filter(User.id != current_user_id).first()
    # 根据对方性别显示称呼
    if other_user:
        if other_user.role in ['girlfriend', '女朋友']:
            partner_name = "女朋友"
        elif other_user.role in ['boyfriend', '男朋友']:
            partner_name = "男朋友"
        else:
            partner_name = other_user.username
    else:
        partner_name = "对方"

    # 获取对方今日操作数量
    partner_actions = GardenService.get_today_actions(other_user.id) if other_user else {}
    partner_actions_count = len([a for a in partner_actions.values() if a['completed']])

    # 构建今日操作状态
    action_status = {}
    for action_type in GardenService.ACTION_BASE_VALUES.keys():
        action_status[action_type] = action_type in today_actions

    return jsonify({
        'success': True,
        'currentUserId': current_user_id,
        'treeData': {
            'level': garden.level,
            'experience': garden.experience,
            'health': round(garden.health, 1),
            'care': round(garden.care, 1),
            'companion': round(garden.companion, 1),
            'love': round(garden.love, 1),
            'sweetness': round(garden.sweetness, 1)
        },
        'todayActions': action_status,
        'partnerName': partner_name,
        'partnerActionsCount': partner_actions_count
    }), 200

@garden_bp.route('/action', methods=['POST'])
@jwt_required()
def perform_action():
    """执行花园操作"""
    current_user_id = get_current_user_id()
    data = request.get_json()
    action_type = data.get('action')
    has_online_bonus = data.get('hasOnlineBonus', False)

    # 使用服务类执行操作
    result = GardenService.perform_action(current_user_id, action_type, has_online_bonus)

    if not result['success']:
        return jsonify(result), 400

    garden = result['garden']
    other_user = result['other_user']

    # 获取当前用户信息
    current_user = User.query.get(current_user_id)

    # 通过WebSocket通知对方（只发送给对方，不发送给操作者自己）
    if other_user:
        socketio.emit('partner_garden_action', {
            'action': action_type,
            'user': current_user.username,
            'userId': current_user_id,  # 添加操作者的用户ID
            'treeData': {
                'level': garden.level,
                'experience': garden.experience,
                'health': round(garden.health, 1),
                'care': round(garden.care, 1),
                'companion': round(garden.companion, 1),
                'love': round(garden.love, 1),
                'sweetness': round(garden.sweetness, 1)
            },
            'levelUp': result['level_up']
        }, room=f'user_{other_user.id}')

    return jsonify({
        'success': True,
        'message': result['message'],
        'treeData': {
            'level': garden.level,
            'experience': garden.experience,
            'health': round(garden.health, 1),
            'care': round(garden.care, 1),
            'companion': round(garden.companion, 1),
            'love': round(garden.love, 1),
            'sweetness': round(garden.sweetness, 1)
        },
        'levelUp': result['level_up'],
        'onlineBonus': result['online_bonus']
    }), 200

@garden_bp.route('/check-settlement', methods=['GET'])
@jwt_required()
def check_settlement():
    """检查是否需要执行每日结算"""
    try:
        # 获取花园数据
        garden = GardenService.get_or_create_garden()

        # 检查是否需要结算
        today = date.today()
        last_updated_date = garden.last_updated.date() if garden.last_updated else None

        # 如果最后更新日期不是今天，说明需要结算昨天的数据
        needs_settlement = last_updated_date != today

        if needs_settlement:
            # 确定要结算的日期
            if last_updated_date is None:
                # 如果从未更新过，结算昨天
                settlement_date = today - timedelta(days=1)
            else:
                # 结算从最后更新日期的下一天到昨天的所有日期
                settlement_date = last_updated_date + timedelta(days=1)

                # 但是为了简化，我们只结算昨天的数据
                # 如果有多天未结算，只按昨天计算惩罚
                settlement_date = today - timedelta(days=1)

            # 自动执行结算
            result = GardenService.apply_daily_settlement(settlement_date)

            if result['success']:
                # 通过WebSocket通知所有用户结算结果
                users = User.query.all()
                garden = result['garden']
                settlement_data = {
                    'type': 'daily_settlement',
                    'message': '每日结算已完成',
                    'penaltyDetails': result['penalty_details'],
                    'totalPenaltyExp': result['total_penalty_exp'],
                    'treeData': {
                        'level': garden.level,
                        'experience': garden.experience,
                        'health': round(garden.health, 1),
                        'care': round(garden.care, 1),
                        'companion': round(garden.companion, 1),
                        'love': round(garden.love, 1),
                        'sweetness': round(garden.sweetness, 1)
                    }
                }

                # 向所有用户发送结算通知
                for user in users:
                    socketio.emit('garden_settlement', settlement_data, room=f'user_{user.id}')

                return jsonify({
                    'success': True,
                    'settlement_executed': True,
                    'message': '每日结算已执行',
                    'penaltyDetails': result['penalty_details'],
                    'totalPenaltyExp': result['total_penalty_exp'],
                    'treeData': settlement_data['treeData']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'settlement_executed': False,
                    'message': '结算执行失败'
                }), 500
        else:
            return jsonify({
                'success': True,
                'settlement_executed': False,
                'message': '今日已结算，无需重复执行'
            }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'settlement_executed': False,
            'message': f'检查结算状态失败: {str(e)}'
        }), 500

@garden_bp.route('/daily-settlement', methods=['POST'])
@jwt_required()
def daily_settlement():
    """手动触发每日结算 (主要用于测试)"""
    # 使用定时任务调度器执行结算
    result = manual_daily_settlement()

    if result and result['success']:
        garden = result['garden']

        return jsonify({
            'success': True,
            'message': '每日结算完成',
            'penaltyDetails': result['penalty_details'],
            'totalPenaltyExp': result['total_penalty_exp'],
            'treeData': {
                'level': garden.level,
                'experience': garden.experience,
                'health': round(garden.health, 1),
                'care': round(garden.care, 1),
                'companion': round(garden.companion, 1),
                'love': round(garden.love, 1),
                'sweetness': round(garden.sweetness, 1)
            }
        }), 200
    else:
        return jsonify({
            'success': False,
            'message': '结算失败'
        }), 500

@garden_bp.route('/reset-scheduler', methods=['POST'])
@jwt_required()
def reset_scheduler():
    """重置定时任务调度器（用于时间修改后的恢复）"""
    try:
        from backend.services.garden_scheduler import reset_garden_scheduler
        reset_garden_scheduler()
        return jsonify({
            'success': True,
            'message': '调度器重置成功'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'调度器重置失败: {str(e)}'
        }), 500
