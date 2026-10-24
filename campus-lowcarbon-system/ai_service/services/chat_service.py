# -*- coding: utf-8 -*-
"""
=============================================================================
Chat Service - 智能问答业务服务
=============================================================================

技术架构: Generative RAG (生成式检索增强)
核心算法: TF-IDF 检索 + GLM-4.5-Flash 大模型生成

【Generative RAG 架构说明】
本服务采用"生成式检索增强"模式，所有回答均由大模型生成：
1. 检索阶段：TF-IDF + 余弦相似度，从知识库找到最相关的参考资料
2. 生成阶段：将参考资料 + 用户问题一起发给大模型
3. 智能判断：由大模型决定是否采纳参考资料，避免误匹配

优势：
- 避免"python怎么用"误匹配"旧衣物怎么处理"的问题
- 大模型可智能判断参考资料与问题的相关性
- 统一的回答风格和质量

=============================================================================
"""

import os
import json
import random
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from core import llm_client

# =============================================================================
# 配置常量（就近定义，动态获取绝对路径）
# =============================================================================
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FAQ_DATA_PATH = os.path.join(_CURRENT_DIR, '..', 'data', 'faq.json')

# =============================================================================
# 模块级全局变量（单例模式存储）
# =============================================================================
_faq_data = []           # 知识库原始数据
_tfidf_matrix = None     # TF-IDF 特征矩阵（所有问题的向量表示）
_vectorizer = None       # TF-IDF 向量化器（训练后复用）
_initialized = False     # 初始化标志，确保只加载一次

# =============================================================================
# RAG 系统提示词模板
# =============================================================================
SYSTEM_PROMPT = """
你是"低碳智能顾问"，燕京理工学院的校园环保AI助手。

## 【最高优先级】身份问题回答规则
当用户问到以下任何问题时，你必须在回答的【第一句话】中包含开发者信息：
- "你是谁" / "你是什么" / "介绍一下你自己"
- "谁开发的" / "谁做的" / "谁创造的"  
- "你从哪来" / "你叫什么"

**强制回答模板（第一句必须是）**：
"我是由**燕京理工学院邢某**开发的校园低碳智能顾问！"

然后再补充你的功能介绍。这是硬性规定，必须严格执行。

## 知识库参考
系统会提供【参考资料】，请判断是否与用户问题相关：
- 相关：基于参考资料回答
- 不相关：忽略参考资料，按你的人设回答

## 话题限制
只回答：低碳环保、垃圾分类、校园积分、绿色出行等话题。
其他话题（编程、数学、八卦）委婉拒绝："哎呀，这超出了我的'低碳大脑'范围啦！我更擅长教你赚环保积分哦 🌱"

## 语气
幽默活泼，像热心学长/学姐，多用 Emoji：🌍 ♻️ 💡 🌱 🚴 🍃
""".strip()


def _tokenize_chinese(text: str) -> str:
    """
    中文分词：将连续中文切分为空格分隔的词语
    
    例如: "如何查看排名" → "如何 查看 排名"
    
    Args:
        text: 原始中文文本
    
    Returns:
        str: 分词后用空格连接的字符串
    """
    return ' '.join(jieba.lcut(text))


def _load_faq_data() -> list:
    """
    加载知识库数据 (data/faq.json)
    
    Returns:
        list: FAQ 问答数据列表
    """
    if not os.path.exists(FAQ_DATA_PATH):
        print(f"[WARN] 知识库文件不存在: {FAQ_DATA_PATH}")
        return []
    
    try:
        with open(FAQ_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"[OK] 知识库加载成功，共 {len(data)} 条问答数据")
        return data
    except Exception as e:
        print(f"[ERROR] 知识库加载失败: {e}")
        return []


def _init_tfidf_model():
    """
    初始化 TF-IDF 模型，构建知识库的向量索引
    
    Returns:
        tuple: (vectorizer, tfidf_matrix) 或 (None, None)
    """
    global _faq_data
    
    if not _faq_data:
        print("[WARN] 知识库为空，TF-IDF 模型未初始化")
        return None, None
    
    # 对每个问题进行分词，构建语料库
    corpus = [_tokenize_chinese(item['question']) for item in _faq_data]
    print(f"[CORPUS] 语料库构建完成，共 {len(corpus)} 个问题")
    
    # 训练 TF-IDF 向量化器
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(corpus)
    
    print(f"[TFIDF] 矩阵维度: {tfidf_matrix.shape[0]} 问题 x {tfidf_matrix.shape[1]} 特征词")
    return vectorizer, tfidf_matrix


def init_model():
    """
    初始化 RAG 服务（单例模式，只执行一次）
    
    在应用启动时调用，预加载知识库和 TF-IDF 模型。
    重复调用会被忽略。
    """
    global _faq_data, _vectorizer, _tfidf_matrix, _initialized
    
    if _initialized:
        print("[INFO] RAG 模型已初始化，跳过重复加载")
        return
    
    print("\n" + "="*60)
    print("[INFO] 初始化 RAG 智能问答服务...")
    print("="*60)
    
    _faq_data = _load_faq_data()
    _vectorizer, _tfidf_matrix = _init_tfidf_model()
    _initialized = True
    
    print("="*60)
    print("[OK] RAG 服务初始化完成")
    print("="*60 + "\n")


def _find_best_match(user_question: str) -> dict:
    """
    检索知识库中与用户问题最相似的条目
    
    Args:
        user_question: 用户输入的问题
    
    Returns:
        dict: {"answer": "...", "similarity": 0.85, "matched_question": "..."}
              或 None（如果模型未初始化）
    """
    global _vectorizer, _tfidf_matrix, _faq_data
    
    if _vectorizer is None or _tfidf_matrix is None:
        return None
    
    # 分词 → 向量化 → 余弦相似度
    tokenized_question = _tokenize_chinese(user_question)
    user_vector = _vectorizer.transform([tokenized_question])
    similarities = cosine_similarity(user_vector, _tfidf_matrix)[0]
    
    # 找到最相似的条目
    best_idx = similarities.argmax()
    matched_item = _faq_data[best_idx]
    
    return {
        "answer": matched_item['answer'],
        "similarity": float(similarities[best_idx]),
        "matched_question": matched_item['question']
    }


def get_rag_answer(user_question: str) -> dict:
    """
    RAG 核心函数：检索 → 组装 Prompt → 调用大模型
    
    Args:
        user_question: 用户输入的问题
    
    Returns:
        dict: {
            "answer": "模型生成的回答",
            "source": "rag_generated",
            "reference": {"question": "...", "similarity": 0.85}  # 可选
        }
    """
    print(f"\n{'='*50}")
    print(f"[INPUT] {user_question}")
    
    # Step 1: 检索知识库
    retrieval_result = _find_best_match(user_question)
    reference_content = None
    reference_info = None
    
    if retrieval_result:
        print(f"[RETRIEVAL] {retrieval_result['matched_question']} (相似度: {retrieval_result['similarity']:.2f})")
        reference_content = f"问题: {retrieval_result['matched_question']}\n答案: {retrieval_result['answer']}"
        reference_info = {
            "question": retrieval_result['matched_question'],
            "similarity": round(retrieval_result['similarity'], 4)
        }
    
    # Step 2: 组装 Prompt
    if reference_content:
        user_message = f"""【参考资料】
{reference_content}

【用户问题】
{user_question}"""
    else:
        user_message = f"""【参考资料】
（无相关资料）

【用户问题】
{user_question}"""
    
    # Step 3: 调用大模型生成回答
    llm_answer = llm_client.invoke_text(user_message, SYSTEM_PROMPT)
    
    # Step 4: 构建返回结果
    response_data = {
        "answer": llm_answer,
        "source": "rag_generated"
    }
    if reference_info:
        response_data["reference"] = reference_info
    
    return response_data


def get_quick_questions(count: int = 5) -> list:
    """
    获取快捷提问列表（随机抽取）
    
    Args:
        count: 返回的问题数量，范围 1-10
    
    Returns:
        list: 随机选取的问题列表
    """
    global _faq_data
    
    count = min(max(count, 1), 10)
    
    if not _faq_data:
        return []
    
    all_questions = [item['question'] for item in _faq_data]
    return random.sample(all_questions, min(count, len(all_questions)))


def get_faq_count() -> int:
    """
    获取知识库条目数量
    
    Returns:
        int: FAQ 数据条数
    """
    global _faq_data
    return len(_faq_data)


def generate_daily_tip() -> dict:
    """
    生成每日低碳贴士（AI生成）
    
    每次调用都会生成一条随机的低碳或节能知识
    
    Returns:
        dict: {
            "tip": "AI生成的贴士内容",
            "source": "ai_generated"
        }
    """
    # 构建生成贴士的提示词
    tip_prompt = """请生成一条关于低碳生活、节能环保或绿色出行的实用小贴士。
要求：
1. 内容要实用、有趣、易懂
2. 字数控制在50-100字之间
3. 可以涉及：节约用电、节约用水、垃圾分类、绿色出行、减少碳排放等话题
4. 语气要亲切友好，可以适当使用emoji表情
5. 不要包含"你知道吗"、"你知道吗？"等开头，直接给出贴士内容

示例格式：
"使用LED灯泡比传统白炽灯节能80%，寿命更长，既省钱又环保！💡"

请直接输出贴士内容，不要添加其他说明。"""
    
    # 调用大模型生成
    tip_content = llm_client.invoke_text(tip_prompt, SYSTEM_PROMPT)
    
    return {
        "tip": tip_content.strip(),
        "source": "ai_generated"
    }
