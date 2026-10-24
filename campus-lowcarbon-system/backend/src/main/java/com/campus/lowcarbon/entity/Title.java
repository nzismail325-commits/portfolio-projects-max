/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 称号实体类
 * 对应数据库表：title
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "title")
@Data
public class Title {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "name", nullable = false, length = 50)
    private String name; // 称号名称
    
    @Column(name = "icon", length = 10)
    private String icon; // 图标（emoji）
    
    @Column(name = "base_cost")
    private Integer baseCost = 100; // 基础解锁费用
    
    @Column(name = "max_level")
    private Integer maxLevel = 5; // 最大等级
    
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

