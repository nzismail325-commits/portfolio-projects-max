# -*- coding: utf-8 -*-
"""
=============================================================================
Config Service - 场景配置服务
=============================================================================

职责：
- 从Spring Boot后端获取场景配置
- 缓存配置数据，减少API调用
- 提供配置刷新功能

=============================================================================
"""

import requests
import time
from typing import Dict, Optional

# Spring Boot后端地址
BACKEND_BASE_URL = "http://localhost:8080/api"

# 配置缓存（scene_type -> config）
_config_cache: Dict[str, Dict] = {}

# 缓存时间戳（scene_type -> timestamp）
_cache_timestamps: Dict[str, float] = {}

# 缓存有效期（秒），默认5分钟
CACHE_TTL = 300


def get_scene_config(scene_type: str, force_refresh: bool = False) -> Optional[Dict]:
    """
    获取场景配置
    
    Args:
        scene_type: 场景类型 ("walk", "ride", "transit", "plate")
        force_refresh: 是否强制刷新缓存
    
    Returns:
        dict: 场景配置，包含以下字段：
            - sceneType: 场景类型
            - icon: 图标
            - title: 标题
            - tag: 标签
            - tagType: 标签类型
            - rewardPoints: 奖励积分
            - requirementText: 要求说明
            - minValue: 最低要求值（步数/里程）
            - unit: 单位
            - keywords: AI判断关键词列表
            - excludeKeywords: 排除关键词列表
    """
    # 检查缓存
    if not force_refresh and scene_type in _config_cache:
        cache_time = _cache_timestamps.get(scene_type, 0)
        if time.time() - cache_time < CACHE_TTL:
            return _config_cache[scene_type]
    
    try:
        # 从后端获取配置
        url = f"{BACKEND_BASE_URL}/scene-config/{scene_type}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200:
                config = data.get("data")
                if config:
                    # 更新缓存
                    _config_cache[scene_type] = config
                    _cache_timestamps[scene_type] = time.time()
                    return config
        
        print(f"[WARN] 获取场景配置失败: {scene_type}, 状态码: {response.status_code}")
        # 如果获取失败，返回缓存中的配置（如果有）
        if scene_type in _config_cache:
            print(f"[INFO] 使用缓存的配置: {scene_type}")
            return _config_cache[scene_type]
        
        return None
        
    except Exception as e:
        print(f"[ERROR] 获取场景配置异常: {scene_type}, 错误: {e}")
        # 如果获取失败，返回缓存中的配置（如果有）
        if scene_type in _config_cache:
            print(f"[INFO] 使用缓存的配置: {scene_type}")
            return _config_cache[scene_type]
        
        return None


def refresh_all_configs():
    """刷新所有场景配置的缓存"""
    scene_types = ["walk", "ride", "transit", "plate"]
    for scene_type in scene_types:
        get_scene_config(scene_type, force_refresh=True)
    print("[INFO] 已刷新所有场景配置缓存")


def get_all_configs() -> Dict[str, Dict]:
    """
    获取所有场景配置
    
    Returns:
        dict: {scene_type: config, ...}
    """
    scene_types = ["walk", "ride", "transit", "plate"]
    configs = {}
    for scene_type in scene_types:
        config = get_scene_config(scene_type)
        if config:
            configs[scene_type] = config
    return configs

