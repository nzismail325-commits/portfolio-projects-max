# -*- coding: utf-8 -*-
"""
=============================================================================
Verify Service - 级联式防作弊验证服务 (4-Step Funnel)
=============================================================================
核心原则：OCR排雷 -> AI最终裁决 (先排雷，再确权) -> 动态积分计算
"""

import hashlib
import io
import re
from typing import Dict, Optional, Tuple
from PIL import Image
import imagehash

from core import llm_client
from services.config_service import get_scene_config

# =============================================================================
# 内存哈希数据库（用于快速检测）
# =============================================================================
_image_hash_db = {
    "walk": {"md5": set(), "phash": []},
    "ride": {"md5": set(), "phash": []},
    "transit": {"md5": set(), "phash": []},
    "plate": {"md5": set(), "phash": []}
}


# =============================================================================
# Step 1: 指纹盾 (Hash Check)
# =============================================================================
def _calculate_md5(file) -> str:
    file.seek(0)
    md5_hash = hashlib.md5()
    for chunk in iter(lambda: file.read(4096), b""):
        md5_hash.update(chunk)
    file.seek(0)
    return md5_hash.hexdigest()


def _calculate_phash(file) -> str:
    file.seek(0)
    image = Image.open(io.BytesIO(file.read()))
    file.seek(0)
    phash = imagehash.phash(image)
    return str(phash)


def _hamming_distance(hash1: str, hash2: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))


def _step1_hash_check(file, scene_type: str) -> Tuple[str, Optional[str]]:
    md5 = _calculate_md5(file)
    phash = _calculate_phash(file)

    if scene_type not in _image_hash_db:
        _image_hash_db[scene_type] = {"md5": set(), "phash": []}
    project_db = _image_hash_db[scene_type]

    if md5 in project_db["md5"]:
        return ("REJECTED", "图片重复提交，该图片已被使用过")

    for stored_phash, _ in project_db["phash"]:
        if _hamming_distance(phash, stored_phash) < 5:
            return ("REJECTED", "图片内容过于相似，疑似重复提交")

    project_db["md5"].add(md5)
    project_db["phash"].append((phash, None))
    return ("PASS", None)


# =============================================================================
# Step 2: 规则引擎 (OCR Check)
# =============================================================================
def _mock_ocr(file, scene_type: str = None) -> str:
    return ""


def _paddle_ocr(file, scene_type: str = None) -> str:
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang='ch')
        file.seek(0)
        image = Image.open(io.BytesIO(file.read()))
        import numpy as np
        img_array = np.array(image)
        result = ocr.ocr(img_array, cls=True)
        texts = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) > 1:
                    texts.append(line[1][0])
        return " ".join(texts)
    except ImportError:
        return _mock_ocr(file, scene_type)
    except Exception as e:
        print(f"[WARN] OCR 识别失败: {e}，使用 Mock")
        return _mock_ocr(file, scene_type)


def _extract_number_from_text(text: str) -> Optional[float]:
    # 提取所有数字
    pattern = r'\d+\.?\d*'
    matches = re.findall(pattern, text)
    if matches:
        try:
            # 过滤掉明显错误的数字（比如年份2023，或者极小的数字），这里简单取最大值
            # 实际场景中，步数通常是整数，里程可能是小数
            numbers = [float(m) for m in matches]
            return max(numbers)
        except:
            return None
    return None


def _step2_ocr_check(file, scene_type: str) -> Tuple[str, Optional[str], Dict]:
    config = get_scene_config(scene_type)
    if not config:
        config = {}

    exclude_keywords = config.get("excludeKeywords", [])

    print(f"[OCR] 开始OCR识别，场景类型: {scene_type}")
    ocr_text = _paddle_ocr(file, scene_type)
    extracted_value = _extract_number_from_text(ocr_text)

    info = {
        "ocr_text": ocr_text,
        "extracted_value": extracted_value
    }

    # 纯文本层面的快速拦截
    if exclude_keywords:
        ocr_text_lower = ocr_text.lower() if ocr_text else ""
        for exclude_keyword in exclude_keywords:
            if exclude_keyword and exclude_keyword.strip():
                keyword_lower = exclude_keyword.strip().lower()
                if keyword_lower in ocr_text_lower:
                    reject_reason = f"OCR拦截：包含排除关键词「{exclude_keyword}」"
                    print(f"[OCR] {scene_type} - {reject_reason}")
                    return ("REJECTED", reject_reason, info)

    print(f"[OCR] OCR检测通过，进入AI视觉复核（提取数值: {extracted_value}）")
    return ("PASS", "OCR文本检测通过，进入AI视觉复核", info)


# =============================================================================
# Step 3: AI 视觉大脑 (VLLM Check)
# =============================================================================
def _step3_vllm_check(file, scene_type: str, ocr_info: Dict) -> Tuple[str, Optional[str], Optional[float]]:
    config = get_scene_config(scene_type)
    if not config:
        config = {}

    title = config.get("title", scene_type)
    requirement_text = config.get("requirementText", "")
    min_value = config.get("minValue")
    unit = config.get("unit", "")
    keywords = config.get("keywords", [])
    exclude_keywords = config.get("excludeKeywords", [])

    ocr_extracted_value = ocr_info.get("extracted_value") if ocr_info else None

    scene_name = title if title else {
        "walk": "健步走",
        "ride": "绿色骑行",
        "transit": "公共交通",
        "plate": "光盘行动"
    }.get(scene_type, scene_type)

    # 1. System Prompt (强调两阶段判断)
    system_prompt = f"""
你是一位严格的审核员，负责审核【{scene_name}】的打卡凭证图片。
你的审核必须严格遵循以下两个阶段的顺序，绝对不可颠倒：

### 第一阶段：排雷检查 (最高优先级)
管理员设置了以下【排除关键词】（Forbidden Items）：
{exclude_keywords}

**规则：**
1. 请仔细检查图片中是否包含上述关键词描述的**物体、场景、或文字**。
2. 只要图片中出现了排除关键词的内容，**必须立即判定为【不通过】**。
3. **如果在第一阶段发现违规，请忽略图片是否符合场景，直接拒绝。**

### 第二阶段：合规检查 (仅当第一阶段通过时执行)
管理员设置了以下【判断关键词】（Required Features）：
{keywords}

**规则：**
1. 图片必须符合【{scene_name}】的场景特征。
2. {f'场景特定要求：{requirement_text}' if requirement_text else ''}

### 输出格式要求
请直接输出结论，格式如下：
结论：通过 / 不通过
原因：(请简要说明原因)
数值：(如果是步数或里程，请提取看到的真实数值；否则填无)
"""

    # 2. User Prompt
    user_prompt_parts = []
    if scene_type == "walk":
        user_prompt_parts.append(f"这是一张健步走打卡图。OCR识别参考值：{ocr_extracted_value}。最低要求：{min_value}步。")
    elif scene_type == "ride":
        user_prompt_parts.append(f"这是一张骑行结束截图。OCR识别参考值：{ocr_extracted_value}。最低要求：{min_value}km。")
    elif scene_type == "transit":
        user_prompt_parts.append("这是一张公共交通凭证，请检查日期是否为今天。")
    elif scene_type == "plate":
        user_prompt_parts.append("这是一张光盘行动照片，盘子必须是空的。")
    else:
        user_prompt_parts.append(f"请判断这张图是否符合{scene_name}的要求。")

    user_prompt_parts.append("\n请严格按照System Prompt的两个阶段进行判断，如果包含排除关键词，请务必拒绝。")

    full_prompt = f"{system_prompt}\n\n{''.join(user_prompt_parts)}"

    # 3. 调用 AI
    print(f"[VLLM] 开始AI视觉验证，场景: {scene_type}")
    result = llm_client.invoke_vision(file, full_prompt)
    print(f"[VLLM] AI原始返回: {result}")

    # 4. 解析结果
    if isinstance(result, dict):
        ai_text = result.get("content", "").strip()
        if not result.get("success", False):
            return ("SUSPICIOUS", "AI调用失败", None)
    else:
        ai_text = str(result).strip()

    # 解析状态
    status = "SUSPICIOUS"
    if "不通过" in ai_text or "拒绝" in ai_text or "结论：不通过" in ai_text:
        status = "REJECTED"
    elif "结论：通过" in ai_text or "通过" in ai_text:
        status = "APPROVED"

    # 解析原因
    reason = "AI未提供具体原因"
    if "原因：" in ai_text:
        reason = ai_text.split("原因：")[1].split("\n")[0].strip()
    elif "原因:" in ai_text:
        reason = ai_text.split("原因:")[1].split("\n")[0].strip()
    else:
        reason = ai_text.replace("\n", " ")[:100]

    # 解析数值 (优先使用AI提取的，因为它能理解上下文，排除掉时间等干扰数字)
    extracted_val = None
    if scene_type in ["walk", "ride"]:
        import re
        # 匹配 "数值：1234" 或 "数值: 1.5"
        val_match = re.search(r'数值[：:]\s*(\d+(?:\.\d+)?)', ai_text)
        if val_match:
            try:
                extracted_val = float(val_match.group(1))
            except:
                pass

        # 兜底：如果AI没填数值，使用OCR的
        if extracted_val is None and ocr_extracted_value is not None:
            extracted_val = ocr_extracted_value

    return (status, reason, extracted_val)


# =============================================================================
# Step 4: Final Response
# =============================================================================
def _step4_final_response(steps_status: list) -> Dict:
    final_status = None
    final_reason = None
    needs_review = False
    rejected_reasons = []

    # 尝试从步骤中找到提取的数值 (通常在AI步骤的信息里)
    final_extracted_value = None

    for step_data in steps_status:
        # step_data结构: (name, status, reason, info)
        if len(step_data) >= 4:
            info = step_data[3]
            if info and "extracted_value" in info and info["extracted_value"] is not None:
                final_extracted_value = info["extracted_value"]

        if len(step_data) >= 3:
            status, reason = step_data[1], step_data[2]
            if status == "REJECTED":
                rejected_reasons.append(reason)
                final_status = "REJECTED"
                if not final_reason: final_reason = reason
            elif status == "SUSPICIOUS" and final_status != "REJECTED":
                final_status = "SUSPICIOUS"
                final_reason = reason
                needs_review = True
            elif status == "APPROVED" and final_status not in ["REJECTED", "SUSPICIOUS"]:
                final_status = "APPROVED"

    if rejected_reasons:
        final_reason = " | ".join(rejected_reasons)

    if final_status is None:
        final_status = "SUSPICIOUS"
        final_reason = "验证流程未知错误"
        needs_review = True

    return {
        "status": final_status,
        "reason": final_reason,
        "needs_review": needs_review,
        "steps": steps_status,
        "extracted_value": final_extracted_value  # 明确返回给前端/调用方
    }


# =============================================================================
# Main Class
# =============================================================================
class VerifyService:
    def __init__(self):
        pass

    def verify_image(self, file, scene_type: str) -> dict:
        steps_status = []

        # 1. Hash Check
        s1_status, s1_reason = _step1_hash_check(file, scene_type)
        steps_status.append(("Hash", s1_status, s1_reason, {}))
        if s1_status == "REJECTED": return _step4_final_response(steps_status)

        # 2. OCR Check
        s2_status, s2_reason, ocr_info = _step2_ocr_check(file, scene_type)
        steps_status.append(("OCR", s2_status, s2_reason, ocr_info))  # 把OCR信息存入
        if s2_status == "REJECTED": return _step4_final_response(steps_status)

        # 3. AI Check
        final_val = None
        if s2_status == "PASS":
            s3_status, s3_reason, s3_val = _step3_vllm_check(file, scene_type, ocr_info)
            final_val = s3_val  # AI提取的值优先级最高
            s3_info = {"extracted_value": s3_val}
            steps_status.append(("AI", s3_status, s3_reason, s3_info))

        # 4. Final Response
        response = _step4_final_response(steps_status)

        # 计算积分 (包含动态奖励)
        if response["status"] == "APPROVED":
            # 如果AI步骤没跑(理论上不可能)或者没提取到，尝试用OCR的值兜底计算
            val_to_use = final_val if final_val is not None else ocr_info.get("extracted_value")
            response["reward"] = self._get_reward(scene_type, val_to_use)

        return response

    def _get_reward(self, scene_type: str, extracted_value: Optional[float]) -> int:
        """
        计算积分奖励（含动态加分）
        公式：基础分 + ((实际值 - 最低要求) // 增量单位) * (基础分 * 增量百分比)
        """
        config = get_scene_config(scene_type)
        if not config:
            return 0

        base_points = config.get("rewardPoints", 0)

        # 如果没有提取到数值，只给基础分
        if extracted_value is None:
            return base_points

        # 获取动态配置参数 (后端返回的是驼峰命名 bonusPercentage)
        min_value = config.get("minValue", 0)
        if min_value is None:
            min_value = 0
        # 增量步数/距离 (后端返回的是驼峰命名 bonusStep)
        bonus_step = config.get("bonusStep")
        if bonus_step is None:
            bonus_step = 0
        else:
            bonus_step = float(bonus_step)
        # 增量百分比 (后端返回的是驼峰命名 bonusPercentage)
        bonus_percentage = config.get("bonusPercentage")
        if bonus_percentage is None:
            bonus_percentage = 0
        else:
            bonus_percentage = float(bonus_percentage)

        # 仅当配置有效且实际值超过最低要求时计算
        if bonus_step > 0 and bonus_percentage > 0 and extracted_value > min_value:
            excess = extracted_value - min_value
            # 计算有多少个完整的增量单位（向下取整）
            units = int(excess // bonus_step)
            if units > 0:
                # 计算总积分 = 基础积分 * (1 + bonusCount * bonusPercentage / 100)
                # 与后端计算逻辑保持一致
                total_multiplier = 1 + (units * bonus_percentage / 100.0)
                total_points = int(base_points * total_multiplier)
                print(
                    f"[Reward] 动态积分触发: 基础{base_points} * {total_multiplier:.2f} = {total_points} (数值:{extracted_value}, 超出:{excess}, 单位数:{units}, 百分比:{bonus_percentage}%)")
                return total_points

        return base_points

    def clear_hash_db(self, scene_type: str = None):
        global _image_hash_db
        if scene_type and scene_type in _image_hash_db:
            _image_hash_db[scene_type]["md5"].clear()
            _image_hash_db[scene_type]["phash"].clear()
        else:
            for db in _image_hash_db.values():
                db["md5"].clear()
                db["phash"].clear()


verify_service = VerifyService()