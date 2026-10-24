/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import java.math.BigDecimal;
import java.util.List;

/**
 * 场景配置DTO
 * 用于前后端数据传输
 * 
 * @author Campus Team
 */
@Data
public class SceneConfigDTO {
    
    private String sceneType; // 场景类型
    private String icon; // 图标
    private String title; // 标题
    private String tag; // 标签
    private String tagType; // 标签类型
    private Integer rewardPoints; // 奖励积分（基础积分）
    private BigDecimal carbonReduction; // 每次打卡减碳量（kg）
    private Integer dailyLimit; // 每天最多打卡次数（0表示不限制）
    private BigDecimal bonusStep; // 每多走多少步/多骑多少km增加积分（仅walk和ride有效）
    private BigDecimal bonusPercentage; // 每达到bonus_step时增加的积分百分比
    private String requirementText; // 要求说明
    private BigDecimal minValue; // 最低要求值
    private String unit; // 单位
    private List<String> keywords; // AI判断关键词
    private List<String> excludeKeywords; // 排除关键词
}

