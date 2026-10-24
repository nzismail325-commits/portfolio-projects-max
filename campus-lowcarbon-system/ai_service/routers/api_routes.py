# -*- coding: utf-8 -*-
"""
=============================================================================
API Routes - RESTful API 路由定义
=============================================================================

职责：
- 定义智能问答、健康检查等 API 端点
- 处理请求参数校验和响应格式化
- 调用 services 层处理业务逻辑

路由前缀: 无（直接挂载到根路径）

=============================================================================
"""

from flask import Blueprint, request, jsonify

from services import chat_service
from services.verify_service import verify_service
from services.config_service import refresh_all_configs

# =============================================================================
# 创建 Blueprint（路由蓝图）
# =============================================================================
api_bp = Blueprint('api', __name__)


# =============================================================================
# 智能问答接口
# =============================================================================

@api_bp.route('/chat', methods=['POST'])
def chat():
    """
    智能问答接口 (Generative RAG)
    
    请求体:
        {
            "question": "用户的问题"
        }
    
    响应:
        {
            "code": 200,
            "data": {
                "answer": "模型生成的回答",
                "source": "rag_generated",
                "reference": {
                    "question": "匹配的知识库问题",
                    "similarity": 0.85
                }
            }
        }
    """
    data = request.get_json()
    
    # 参数校验
    if not data or 'question' not in data:
        return jsonify({"code": 400, "message": "缺少 question 字段"}), 400
    
    user_question = data['question'].strip()
    if not user_question:
        return jsonify({"code": 400, "message": "问题不能为空"}), 400
    
    # 调用业务层处理
    response_data = chat_service.get_rag_answer(user_question)
    
    return jsonify({"code": 200, "data": response_data})


@api_bp.route('/quick-questions', methods=['GET'])
def get_quick_questions():
    """
    获取快捷提问列表（随机抽取）
    
    查询参数:
        count: 返回数量，默认 5，范围 1-10
    
    响应:
        {
            "code": 200,
            "data": ["问题1", "问题2", ...]
        }
    """
    count = request.args.get('count', 5, type=int)
    
    # 调用业务层处理
    questions = chat_service.get_quick_questions(count)
    
    return jsonify({"code": 200, "data": questions})


@api_bp.route('/daily-tip', methods=['GET'])
def get_daily_tip():
    """
    获取每日低碳贴士（AI生成）
    
    响应:
        {
            "code": 200,
            "data": {
                "tip": "AI生成的低碳贴士内容",
                "source": "ai_generated"
            }
        }
        或
        {
            "code": 500,
            "message": "错误信息"
        }
    """
    try:
        # 调用业务层生成贴士
        tip_data = chat_service.generate_daily_tip()
        return jsonify({"code": 200, "data": tip_data})
    except Exception as e:
        print(f"[ERROR] 生成每日贴士失败: {e}")
        return jsonify({
            "code": 500,
            "message": f"生成贴士失败: {str(e)}"
        }), 500


# =============================================================================
# 健康检查接口
# =============================================================================

@api_bp.route('/health', methods=['GET'])
def health_check():
    """
    健康检查接口
    
    响应:
        {
            "code": 200,
            "status": "healthy",
            "faq_count": 知识库条目数
        }
    """
    return jsonify({
        "code": 200,
        "status": "healthy",
        "faq_count": chat_service.get_faq_count()
    })


# =============================================================================
# 图片验证接口（级联式防作弊验证）
# =============================================================================

@api_bp.route('/verify', methods=['POST'])
def verify_image():
    """
    图片验证接口（4步级联式防作弊验证）
    
    请求:
        - Content-Type: multipart/form-data
        - 参数:
            - image: 图片文件（必填）
            - scene_type: 场景类型（必填），可选值: "walk", "ride", "transit", "plate"
    
    响应:
        {
            "code": 200,
            "data": {
                "status": "APPROVED" | "REJECTED" | "SUSPICIOUS",
                "reason": "拒绝理由" | null,
                "needs_review": true/false,
                "reward": 积分奖励（仅当 status=APPROVED 时存在）,
                "steps": [
                    {
                        "step": "Hash Check",
                        "status": "PASS" | "REJECTED",
                        "reason": "理由"
                    },
                    ...
                ]
            }
        }
    """
    # 检查是否有文件
    if 'image' not in request.files:
        return jsonify({"code": 400, "message": "缺少 image 文件"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"code": 400, "message": "文件名为空"}), 400
    
    # 获取场景类型
    scene_type = request.form.get('scene_type', '').strip().lower()
    if not scene_type:
        return jsonify({"code": 400, "message": "缺少 scene_type 参数"}), 400
    
    # 验证场景类型
    valid_scenes = ['walk', 'ride', 'transit', 'plate']
    if scene_type not in valid_scenes:
        return jsonify({
            "code": 400, 
            "message": f"scene_type 必须是以下值之一: {', '.join(valid_scenes)}"
        }), 400
    
    # 检查文件类型
    if not file.content_type or not file.content_type.startswith('image/'):
        return jsonify({"code": 400, "message": "文件必须是图片格式"}), 400
    
    # 检查文件大小（5MB）
    file.seek(0, 2)  # 移动到文件末尾
    file_size = file.tell()
    file.seek(0)     # 重置文件指针
    
    if file_size > 5 * 1024 * 1024:  # 5MB
        return jsonify({"code": 400, "message": "图片大小不能超过 5MB"}), 400
    
    try:
        # 调用验证服务
        result = verify_service.verify_image(file, scene_type)
        
        # 格式化响应
        formatted_steps = []
        for step_data in result.get("steps", []):
            step_dict = {
                "step": step_data[0],
                "status": step_data[1],
                "reason": step_data[2] if len(step_data) > 2 else None
            }
            # 如果有额外的info信息（包含extracted_value），添加到步骤中
            if len(step_data) > 3 and isinstance(step_data[3], dict):
                step_dict.update(step_data[3])
            formatted_steps.append(step_dict)
        
        response_data = {
            "status": result["status"],
            "reason": result.get("reason"),
            "needs_review": result.get("needs_review", False),
            "steps": formatted_steps
        }
        
        # 如果通过验证，添加积分奖励
        if result.get("status") == "APPROVED" and "reward" in result:
            response_data["reward"] = result["reward"]
        
        return jsonify({"code": 200, "data": response_data})
        
    except Exception as e:
        print(f"[ERROR] 图片验证失败: {e}")
        return jsonify({
            "code": 500,
            "message": f"验证过程出错: {str(e)}"
        }), 500


# =============================================================================
# 测试接口（用于清除哈希数据）
# =============================================================================

@api_bp.route('/verify/clear', methods=['POST'])
def clear_verify_data():
    """
    清除验证哈希数据（测试接口）
    
    请求体（可选）:
        {
            "scene_type": "walk" | "ride" | "transit" | "plate"  // 如果指定，只清除该项目的；如果不指定，清除所有
        }
    
    响应:
        {
            "code": 200,
            "message": "清除结果",
            "data": {
                "stats": {...}  // 清除后的统计信息
            }
        }
    """
    try:
        data = request.get_json() or {}
        scene_type = data.get('scene_type', None)
        
        # 清除数据
        message = verify_service.clear_hash_db(scene_type)
        
        # 获取清除后的统计信息
        stats = verify_service.get_hash_db_stats()
        
        return jsonify({
            "code": 200,
            "message": message,
            "data": {
                "stats": stats
            }
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"清除数据失败: {str(e)}"
        }), 500


@api_bp.route('/verify/stats', methods=['GET'])
def get_verify_stats():
    """
    获取验证哈希数据统计信息（调试接口）
    
    响应:
        {
            "code": 200,
            "data": {
                "stats": {
                    "walk": {"md5_count": 0, "phash_count": 0},
                    "ride": {"md5_count": 0, "phash_count": 0},
                    ...
                }
            }
        }
    """
    try:
        stats = verify_service.get_hash_db_stats()
        return jsonify({
            "code": 200,
            "data": {
                "stats": stats
            }
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"获取统计信息失败: {str(e)}"
        }), 500


# =============================================================================
# 配置刷新接口（用于管理员修改配置后刷新AI服务缓存）
# =============================================================================

@api_bp.route('/config/refresh', methods=['POST'])
def refresh_config():
    """
    刷新场景配置缓存（管理员修改配置后调用）
    
    响应:
        {
            "code": 200,
            "message": "配置已刷新"
        }
    """
    try:
        refresh_all_configs()
        return jsonify({
            "code": 200,
            "message": "配置已刷新"
        })
    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"刷新配置失败: {str(e)}"
        }), 500


# =============================================================================
# 数据分析接口（全局看板）
# =============================================================================

@api_bp.route('/dashboard/analyze-scene-participation', methods=['POST'])
def analyze_scene_participation():
    """
    分析场景参与占比数据（AI分析）
    
    请求体:
        {
            "data": [
                {
                    "sceneType": "walk",
                    "sceneName": "低碳健步走",
                    "count": 350,
                    "percentage": 35.0
                },
                ...
            ],
            "timeRange": "today" | "week" | "month"
        }
    
    响应:
        {
            "code": 200,
            "data": {
                "analysis": "AI分析结果文本",
                "insights": ["洞察1", "洞察2", ...],
                "recommendations": ["建议1", "建议2", ...]
            }
        }
    """
    try:
        data = request.get_json()
        
        if not data or 'data' not in data:
            return jsonify({"code": 400, "message": "缺少 data 字段"}), 400
        
        participation_data = data.get('data', [])
        time_range = data.get('timeRange', 'today')
        
        if not participation_data:
            return jsonify({"code": 400, "message": "数据为空"}), 400
        
        # 构建分析提示词
        scene_info = "\n".join([
            f"- {item.get('sceneName', '')}: {item.get('percentage', 0):.1f}% ({item.get('count', 0)}次)"
            for item in participation_data
        ])
        
        time_range_map = {
            "today": "今日",
            "week": "本周",
            "month": "本月"
        }
        time_range_text = time_range_map.get(time_range, "今日")
        
        prompt = f"""请分析以下{time_range_text}五大场景参与占比数据，并提供专业的分析报告：

{scene_info}

请从以下角度进行分析：
1. 各场景参与度的分布特点
2. 可能的原因分析
3. 改进建议

要求：
- 分析要客观、专业
- 提供2-3条关键洞察
- 提供2-3条改进建议
- 语言简洁明了，适合管理员阅读
- 总字数控制在100字以内"""
        
        # 调用LLM进行分析
        from core.llm_client import invoke_text
        analysis_text = invoke_text(
            prompt=prompt,
            system_prompt="你是一位数据分析专家，擅长分析用户行为数据和提供改进建议。"
        )
        
        # 提取洞察和建议（简单处理，实际可以使用更复杂的解析）
        insights = []
        recommendations = []
        
        # 简单的文本解析（实际项目中可以使用更智能的方法）
        lines = analysis_text.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            if '洞察' in line or 'insight' in line.lower() or '特点' in line:
                current_section = 'insights'
            elif '建议' in line or 'recommendation' in line.lower() or '改进' in line:
                current_section = 'recommendations'
            elif line and line.startswith(('1.', '2.', '3.', '-', '•')):
                if current_section == 'insights':
                    insights.append(line.lstrip('123.-• '))
                elif current_section == 'recommendations':
                    recommendations.append(line.lstrip('123.-• '))
        
        # 如果没有解析到，使用默认值
        if not insights:
            insights = ["各场景参与度分布较为均衡", "健步走场景参与度最高"]
        if not recommendations:
            recommendations = ["可以加大对参与度较低场景的宣传力度", "考虑设置场景参与奖励机制"]
        
        return jsonify({
            "code": 200,
            "data": {
                "analysis": analysis_text,
                "insights": insights[:3],  # 最多3条
                "recommendations": recommendations[:3]  # 最多3条
            }
        })
        
    except Exception as e:
        print(f"[ERROR] 分析场景参与占比失败: {e}")
        return jsonify({
            "code": 500,
            "message": f"分析失败: {str(e)}"
        }), 500


@api_bp.route('/dashboard/analyze-activity-trend', methods=['POST'])
def analyze_activity_trend():
    """
    分析活跃度趋势数据（AI分析）
    
    请求体:
        {
            "data": [
                {
                    "date": "12-11",
                    "activeUsers": 892,
                    "checkinCount": 1200
                },
                ...
            ]
        }
    
    响应:
        {
            "code": 200,
            "data": {
                "analysis": "AI分析结果文本",
                "trend": "上升" | "下降" | "平稳",
                "peakDay": "峰值日期",
                "insights": ["洞察1", "洞察2", ...]
            }
        }
    """
    try:
        data = request.get_json()
        
        if not data or 'data' not in data:
            return jsonify({"code": 400, "message": "缺少 data 字段"}), 400
        
        activity_data = data.get('data', [])
        
        if not activity_data or len(activity_data) < 2:
            return jsonify({"code": 400, "message": "数据不足，至少需要2天的数据"}), 400
        
        # 构建分析提示词
        activity_info = "\n".join([
            f"{item.get('date', '')}: 活跃用户{item.get('activeUsers', 0)}人, 打卡{item.get('checkinCount', 0)}次"
            for item in activity_data
        ])
        
        # 计算趋势
        first_day_users = activity_data[0].get('activeUsers', 0)
        last_day_users = activity_data[-1].get('activeUsers', 0)
        trend = "平稳"
        if last_day_users > first_day_users * 1.1:
            trend = "上升"
        elif last_day_users < first_day_users * 0.9:
            trend = "下降"
        
        # 找出峰值日期
        peak_day = max(activity_data, key=lambda x: x.get('activeUsers', 0))
        peak_date = peak_day.get('date', '')
        
        prompt = f"""请分析以下近七日系统活跃度数据，并提供专业的趋势分析报告：

{activity_info}

请从以下角度进行分析：
1. 整体趋势分析（上升/下降/平稳）
2. 峰值出现的原因分析
3. 可能的影响因素
4. 预测和建议

要求：
- 分析要客观、专业
- 提供2-3条关键洞察
- 语言简洁明了，适合管理员阅读
- 总字数控制在150字以内"""
        
        # 调用LLM进行分析
        from core.llm_client import invoke_text
        analysis_text = invoke_text(
            prompt=prompt,
            system_prompt="你是一位数据分析专家，擅长分析时间序列数据和趋势预测。"
        )
        
        # 提取洞察（简单处理）
        insights = []
        lines = analysis_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if line and (line.startswith(('1.', '2.', '3.', '-', '•')) or '趋势' in line or '峰值' in line):
                insights.append(line.lstrip('123.-• '))
        
        if not insights:
            insights = [f"整体趋势：{trend}", f"峰值出现在{peak_date}"]
        
        return jsonify({
            "code": 200,
            "data": {
                "analysis": analysis_text,
                "trend": trend,
                "peakDay": peak_date,
                "insights": insights[:3]  # 最多3条
            }
        })
        
    except Exception as e:
        print(f"[ERROR] 分析活跃度趋势失败: {e}")
        return jsonify({
            "code": 500,
            "message": f"分析失败: {str(e)}"
        }), 500


@api_bp.route('/dashboard/analyze-personal-data', methods=['POST'])
def analyze_personal_data():
    """
    分析个人数据（AI分析）- 接收后端计算结果，生成专业分析报告
    
    请求体:
        {
            "calculation": {
                "checkinTrendAnalysis": {
                    "averageDailyCheckins": 2.5,
                    "maxDailyCheckins": 4,
                    "minDailyCheckins": 1,
                    "trend": "上升",
                    "trendRate": 15.5,
                    "consecutiveDays": 5,
                    "activeDays": 6,
                    "consistency": "良好"
                },
                "sceneDistributionAnalysis": {
                    "favoriteScene": "低碳健步走",
                    "favoriteScenePercentage": 45.0,
                    "leastFavoriteScene": "公共交通",
                    "leastFavoriteScenePercentage": 10.0,
                    "diversityScore": 75.0,
                    "diversityLevel": "高",
                    "missingScenes": []
                },
                "carbonReductionAnalysis": {
                    "totalCarbonReduction": 15.7,
                    "averageDailyCarbonReduction": 2.6,
                    "monthlyCarbonReduction": 5.2,
                    "weeklyCarbonReduction": 2.1,
                    "monthlyGrowthRate": 12.5,
                    "weeklyGrowthRate": 8.3,
                    "contributionLevel": "良好",
                    "equivalentDescription": "相当于种植1棵树"
                },
                "pointsAnalysis": {
                    "totalPoints": 500,
                    "monthlyPoints": 150,
                    "weeklyPoints": 60,
                    "averageDailyPoints": 10.0,
                    "maxDailyPoints": 25,
                    "monthlyGrowthRate": 15.0,
                    "weeklyGrowthRate": 10.0,
                    "activityLevel": "中"
                },
                "overallAssessment": {
                    "overallLevel": "良好",
                    "overallScore": 75,
                    "strengths": ["打卡习惯良好", "场景参与多样化"],
                    "weaknesses": ["活跃度有待提升"],
                    "summary": "综合得分75分，等级为良好..."
                }
            },
            "rawData": {
                "checkinTrend": [...],
                "sceneDistribution": [...],
                "carbonStats": {...},
                "pointsTrend": {...}
            }
        }
    
    响应:
        {
            "code": 200,
            "data": {
                "analysis": "AI生成的详细分析报告",
                "insights": ["洞察1", "洞察2", ...],
                "recommendations": ["建议1", "建议2", ...]
            }
        }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"code": 400, "message": "请求体不能为空"}), 400
        
        calculation = data.get('calculation', {})
        raw_data = data.get('rawData', {})
        
        if not calculation:
            return jsonify({"code": 400, "message": "缺少calculation字段"}), 400
        
        # 提取计算结果
        checkin_analysis = calculation.get('checkinTrendAnalysis', {})
        scene_analysis = calculation.get('sceneDistributionAnalysis', {})
        carbon_analysis = calculation.get('carbonReductionAnalysis', {})
        points_analysis = calculation.get('pointsAnalysis', {})
        overall = calculation.get('overallAssessment', {})
        
        # 构建专业的分析提示词
        prompt_parts = []
        
        # 综合评估
        if overall:
            prompt_parts.append(f"""【综合评估】
综合得分：{overall.get('overallScore', 0)}分
综合等级：{overall.get('overallLevel', '未知')}
优势点：{', '.join(overall.get('strengths', []))}
待改进点：{', '.join(overall.get('weaknesses', []))}
总结：{overall.get('summary', '')}""")
        
        # 打卡趋势分析
        if checkin_analysis:
            prompt_parts.append(f"""【打卡趋势分析】
平均每日打卡：{checkin_analysis.get('averageDailyCheckins', 0):.1f}次
单日最高打卡：{checkin_analysis.get('maxDailyCheckins', 0)}次
单日最低打卡：{checkin_analysis.get('minDailyCheckins', 0)}次
整体趋势：{checkin_analysis.get('trend', '未知')}（变化率{checkin_analysis.get('trendRate', 0):.1f}%）
连续打卡天数：{checkin_analysis.get('consecutiveDays', 0)}天
活跃天数：{checkin_analysis.get('activeDays', 0)}天
一致性评价：{checkin_analysis.get('consistency', '未知')}""")
        
        # 场景分布分析
        if scene_analysis:
            missing_scenes = scene_analysis.get('missingScenes', [])
            missing_text = f"，未参与场景：{', '.join(missing_scenes)}" if missing_scenes else "，已覆盖所有场景"
            prompt_parts.append(f"""【场景分布分析】
最偏好场景：{scene_analysis.get('favoriteScene', '未知')}（占比{scene_analysis.get('favoriteScenePercentage', 0):.1f}%）
最少参与场景：{scene_analysis.get('leastFavoriteScene', '未知')}（占比{scene_analysis.get('leastFavoriteScenePercentage', 0):.1f}%）
多样性得分：{scene_analysis.get('diversityScore', 0):.1f}分
多样性等级：{scene_analysis.get('diversityLevel', '未知')}{missing_text}""")
        
        # 减碳量分析
        if carbon_analysis:
            prompt_parts.append(f"""【减碳量分析】
累计减碳量：{carbon_analysis.get('totalCarbonReduction', 0):.2f}kg
平均每日减碳：{carbon_analysis.get('averageDailyCarbonReduction', 0):.2f}kg
本月减碳量：{carbon_analysis.get('monthlyCarbonReduction', 0):.2f}kg（增长率{carbon_analysis.get('monthlyGrowthRate', 0):.1f}%）
本周减碳量：{carbon_analysis.get('weeklyCarbonReduction', 0):.2f}kg（增长率{carbon_analysis.get('weeklyGrowthRate', 0):.1f}%）
贡献等级：{carbon_analysis.get('contributionLevel', '未知')}
环保贡献：{carbon_analysis.get('equivalentDescription', '')}""")
        
        # 积分分析
        if points_analysis:
            prompt_parts.append(f"""【积分分析】
总积分：{points_analysis.get('totalPoints', 0)}分
本月积分：{points_analysis.get('monthlyPoints', 0)}分（增长率{points_analysis.get('monthlyGrowthRate', 0):.1f}%）
本周积分：{points_analysis.get('weeklyPoints', 0)}分（增长率{points_analysis.get('weeklyGrowthRate', 0):.1f}%）
平均每日积分：{points_analysis.get('averageDailyPoints', 0):.1f}分
单日最高积分：{points_analysis.get('maxDailyPoints', 0)}分
活跃度等级：{points_analysis.get('activityLevel', '未知')}""")
        
        if not prompt_parts:
            return jsonify({"code": 400, "message": "分析数据为空"}), 400
        
        full_prompt = "\n\n".join(prompt_parts)
        
        # 构建专业的AI分析提示词
        prompt = f"""作为一位专业的环保数据分析专家，请基于以下详细的计算分析结果，生成一份专业、全面、个性化的个人低碳行为分析报告,尽量精简子字数，且尽量不超过两百五十字。

{full_prompt}

请从以下维度进行深度分析：

1. **打卡行为分析**
   - 评估打卡习惯的规律性和持续性
   - 分析趋势变化的原因和意义
   - 评价打卡频率的合理性

2. **场景参与分析**
   - 分析场景偏好形成的原因
   - 评估场景多样性的价值
   - 指出场景参与的优化空间

3. **减碳贡献评估**
   - 量化个人环保贡献
   - 分析减碳量的增长趋势
   - 评估在环保行动中的表现

4. **活跃度评估**
   - 分析积分获取的积极性
   - 评估参与频率和持续性
   - 指出提升空间

5. **综合建议**
   - 基于综合评估结果，提供3-5条具体、可执行的改进建议
   - 建议要针对性强，有实际指导意义
   - 语言要鼓励性、建设性

要求：
- 分析要专业、全面、深入
- 语言要亲切友好，适合学生阅读
- 提供3-5条关键洞察（每条20字）
- 提供3-5条改进建议（每条20字）
- 总分析报告控制在二百七十字
- 要结合具体数据进行分析，避免空泛的表述"""
        
        # 调用LLM进行分析
        from core.llm_client import invoke_text
        analysis_text = invoke_text(
            prompt=prompt,
            system_prompt="你是一位专业的环保数据分析专家和教育顾问，擅长基于数据分析结果提供深入、专业、个性化的环保行为分析和改进建议。你的分析要客观、专业、有深度，同时要鼓励性和建设性。"
        )
        
        # 提取洞察和建议（更智能的解析）
        insights = []
        recommendations = []
        lines = analysis_text.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            # 识别章节
            if '洞察' in line or 'insight' in line.lower() or '关键发现' in line or '特点' in line or '亮点' in line:
                current_section = 'insights'
            elif '建议' in line or 'recommendation' in line.lower() or '改进' in line or '优化' in line or '提升' in line:
                current_section = 'recommendations'
            # 提取内容
            elif line and (line.startswith(('1.', '2.', '3.', '4.', '5.', '-', '•', '·', '▪')) or 
                          (current_section and len(line) > 10 and not line.startswith('【'))):
                content = line.lstrip('12345.-•·▪ ')
                if content and len(content) > 5:  # 过滤太短的内容
                    if current_section == 'insights':
                        insights.append(content)
                    elif current_section == 'recommendations':
                        recommendations.append(content)
        
        # 如果没有解析到，尝试从全文提取
        if not insights or not recommendations:
            # 尝试从分析文本中提取关键句子
            sentences = analysis_text.replace('。', '。\n').split('\n')
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence or len(sentence) < 10:
                    continue
                # 判断是洞察还是建议
                if any(keyword in sentence for keyword in ['表现', '特点', '优势', '亮点', '突出', '优秀', '良好']):
                    if len(insights) < 5:
                        insights.append(sentence)
                elif any(keyword in sentence for keyword in ['建议', '可以', '应该', '尝试', '提升', '改进', '优化', '增加']):
                    if len(recommendations) < 5:
                        recommendations.append(sentence)
        
        # 如果还是没有，使用默认值
        if not insights:
            insights = [
                f"综合得分{overall.get('overallScore', 0)}分，等级为{overall.get('overallLevel', '未知')}",
                f"打卡一致性评价：{checkin_analysis.get('consistency', '未知')}",
                f"场景多样性等级：{scene_analysis.get('diversityLevel', '未知')}"
            ]
        if not recommendations:
            recommendations = [
                "建议保持每日打卡的连续性，形成良好的低碳习惯",
                "可以尝试更多不同的低碳场景，提升参与多样性",
                "继续保持当前良好的环保行为，为地球贡献更多力量"
            ]
        
        return jsonify({
            "code": 200,
            "data": {
                "analysis": analysis_text,
                "insights": insights[:5],  # 最多5条
                "recommendations": recommendations[:5]  # 最多5条
            }
        })
        
    except Exception as e:
        print(f"[ERROR] 分析个人数据失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "code": 500,
            "message": f"分析失败: {str(e)}"
        }), 500
