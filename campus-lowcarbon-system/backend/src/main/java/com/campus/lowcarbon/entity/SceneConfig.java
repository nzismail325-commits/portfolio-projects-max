/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 场景配置实体类
 * 对应数据库表：scene_config
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "scene_config")
@Data
public class SceneConfig {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "scene_type", unique = true, nullable = false, length = 20)
    private String sceneType; // 场景类型：walk-健步走，ride-骑行，plate-光盘，transit-公共交通
    
    @Column(name = "icon", length = 10)
    private String icon; // 图标（emoji）
    
    @Column(name = "title", length = 50)
    private String title; // 标题
    
    @Column(name = "tag", length = 50)
    private String tag; // 标签
    
    @Column(name = "tag_type", length = 20)
    private String tagType; // 标签类型
    
    @Column(name = "reward_points")
    private Integer rewardPoints = 10; // 奖励积分
    
    @Column(name = "carbon_reduction", precision = 10, scale = 4)
    private BigDecimal carbonReduction = new BigDecimal("0.3925"); // 每次打卡减碳量（kg）
    
    @Column(name = "daily_limit")
    private Integer dailyLimit = 3; // 每天最多打卡次数（0表示不限制）
    
    @Column(name = "bonus_step", precision = 10, scale = 2)
    private BigDecimal bonusStep; // 每多走多少步/多骑多少km增加积分（仅walk和ride有效）
    
    @Column(name = "bonus_percentage", precision = 5, scale = 2)
    private BigDecimal bonusPercentage = new BigDecimal("10.00"); // 每达到bonus_step时增加的积分百分比
    
    @Column(name = "requirement_text", columnDefinition = "TEXT")
    private String requirementText; // 要求说明
    
    @Column(name = "min_value", precision = 10, scale = 2)
    private BigDecimal minValue; // 最低要求值（步数/里程）
    
    @Column(name = "unit", length = 10)
    private String unit; // 单位
    
    @Column(name = "keywords", columnDefinition = "JSON")
    private String keywords; // AI判断关键词（JSON数组字符串）
    
    @Column(name = "exclude_keywords", columnDefinition = "JSON")
    private String excludeKeywords; // 排除关键词（JSON数组字符串）
    
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 创建时间
    
    @Column(name = "updated_at")
    private LocalDateTime updatedAt; // 更新时间
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }
    
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}

