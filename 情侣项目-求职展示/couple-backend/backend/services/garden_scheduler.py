"""
爱情花园定时任务
实现每日凌晨的自动结算功能
"""

import logging
import time
from datetime import datetime, date, timedelta

from backend.extensions import socketio
from backend.models import User
from backend.services.garden_service import GardenService

logger = logging.getLogger(__name__)


def _notify_settlement_result(result):
    """通过WebSocket通知所有用户结算结果"""
    try:
        garden = result['garden']
        settlement_data = {
            'type': 'daily_settlement',
            'message': '每日结算已完成',
            'penaltyDetails': result.get('penalty_details', {}),
            'totalPenaltyExp': result.get('total_penalty_exp', 0),
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

        users = User.query.all()
        for user in users:
            socketio.emit('garden_settlement', settlement_data, room=f'user_{user.id}')

        logger.info("已向所有用户发送结算通知")

    except Exception as e:
        logger.error(f"发送结算通知失败: {e}", exc_info=True)


def background_scheduler_loop(app):
    """
    后台调度器主循环。
    这个任务由 flask-socketio 启动，以确保它在gevent环境中安全运行。
    """
    logger.info("后台花园调度器已启动...")
    last_run_date = date.today()

    while True:
        try:
            today = date.today()
            # 如果是新的一天，并且时间是午夜之后
            if today != last_run_date:
                logger.info(f"检测到新的一天: {today}。准备执行午夜结算。")
                with app.app_context():
                    # 结算昨天的数据
                    yesterday = today - timedelta(days=1)
                    result = GardenService.apply_daily_settlement(yesterday)

                    if result['success']:
                        logger.info(f"每日结算成功, 经验惩罚: {result.get('total_penalty_exp', 0)}")
                        # 在同一个app_context中发送通知
                        _notify_settlement_result(result)
                    else:
                        logger.error(f"每日结算失败: {result.get('message')}")
                
                # 无论成功与否，都标记今天已经运行过，防止重复执行
                last_run_date = today

            # 每分钟检查一次，这个时间可以根据需要调整
            socketio.sleep(60)

        except Exception as e:
            logger.error(f"后台调度器循环出错: {e}", exc_info=True)
            # 即使出错，也等待一段时间再继续，防止CPU占用过高
            socketio.sleep(60)


def manual_daily_settlement(target_date=None):
    """
    手动触发每日结算 (用于测试)
    注意: 这个函数会直接导入主app，只应该在明确的请求上下文中使用（例如测试用的API端点）
    """
    from backend.app import app
    try:
        with app.app_context():
            if target_date is None:
                target_date = date.today() - timedelta(days=1)

            logger.info(f"手动触发结算，目标日期: {target_date}")
            result = GardenService.apply_daily_settlement(target_date)

            if result['success']:
                logger.info(f"手动结算完成，经验惩罚: {result.get('total_penalty_exp', 0)}")
                _notify_settlement_result(result)
                return result
            else:
                logger.error(f"手动结算失败: {result.get('message')}")
                return None
    except Exception as e:
        logger.error(f"手动结算执行失败: {e}", exc_info=True)
        return None
