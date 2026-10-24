# -*- coding: utf-8 -*-
"""
=============================================================================
LLM Client - 大语言模型调用封装
=============================================================================

职责：
- 封装智谱 AI (GLM-4.5-Flash) 的调用逻辑
- 提供文本生成和视觉理解的统一接口

配置说明：
- API Key 就近定义在本文件顶部，便于管理

=============================================================================
"""

import os

from zai import ZhipuAiClient

# =============================================================================
# 配置常量（就近定义，不使用独立 config.py）
# =============================================================================
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")

# =============================================================================
# 初始化客户端（模块加载时创建单例）
# =============================================================================
_client = ZhipuAiClient(api_key=ZHIPU_API_KEY)


def invoke_text(prompt: str, system_prompt: str = None) -> str:
    """
    调用 GLM-4.5-Flash 进行文本生成
    
    Args:
        prompt: 用户输入的问题/提示词
        system_prompt: 系统角色设定（可选）
    
    Returns:
        str: 模型生成的回答文本
    """
    try:
        print(f"[LLM] 调用 GLM-4.5-Flash...")
        
        messages = []
        
        # 添加系统提示词
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        # 添加用户消息
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        response = _client.chat.completions.create(
            model="glm-4.5-flash",  # 免费高速版本
            messages=messages,
            stream=False,      # 非流式，直接返回完整结果
            temperature=0.7    # 平衡创造性与准确性
        )
        
        # 提取回答内容
        answer = response.choices[0].message.content
        print(f"[LLM] 模型回复成功，长度: {len(answer)} 字符")
        return answer
        
    except Exception as e:
        print(f"[ERROR] GLM 模型调用失败: {e}")
        return "抱歉，智能顾问暂时开小差了~ 请稍后再试，或直接咨询人工客服哦！"


def invoke_vision(image_file, prompt: str = None) -> dict:
    """
    调用视觉模型进行图片理解
    
    使用智谱 AI 的 GLM-4.6V-Flash 视觉模型分析图片。
    
    Args:
        image_file: 图片文件对象（支持文件对象或文件路径）
        prompt: 对图片的分析指令（默认：请描述这个图片）
    
    Returns:
        dict: {
            "content": "AI 返回的分析文本",
            "model": "glm-4.6v-flash",
            "success": True/False
        }
    """
    import base64
    import io
    
    try:
        print(f"[VLLM] 调用 GLM-4.6V-Flash 视觉模型...")
        
        # 处理图片文件：转换为 base64
        if hasattr(image_file, 'read'):
            # 文件对象
            image_file.seek(0)
            img_bytes = image_file.read()
            image_file.seek(0)
        elif isinstance(image_file, str):
            # 文件路径
            with open(image_file, 'rb') as f:
                img_bytes = f.read()
        else:
            # 假设是 bytes
            img_bytes = image_file
        
        # 转换为 base64
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        # 默认 prompt
        if not prompt:
            prompt = "请描述这个图片"
        
        # 构建消息
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": img_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
        
        # 调用视觉模型
        response = _client.chat.completions.create(
            model="glm-4.6v-flash",  # 视觉模型
            messages=messages,
            thinking={
                "type": "enabled"
            }
        )
        
        # 提取回答内容
        content = response.choices[0].message.content
        print(f"[VLLM] 视觉模型回复成功，长度: {len(content)} 字符")
        
        return {
            "content": content,
            "model": "glm-4.6v-flash",
            "success": True
        }
        
    except Exception as e:
        print(f"[ERROR] 视觉模型调用失败: {e}")
        return {
            "content": "视觉模型调用失败，请稍后重试",
            "model": "glm-4.6v-flash",
            "success": False,
            "error": str(e)
        }
