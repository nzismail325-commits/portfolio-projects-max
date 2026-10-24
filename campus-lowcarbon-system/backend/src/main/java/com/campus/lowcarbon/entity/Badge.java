/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 勋章实体类
 * 对应数据库表：badge
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "badge")
@Data
public class Badge {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "name", nullable = false, length = 50)
    private String name; // 勋章名称
    
    @Column(name = "icon", length = 10)
    private String icon; // 图标（emoji）
    
    @Column(name = "type", nullable = false, length = 20)
    private String type; // 类型：plate-光盘系列，walk-健步系列，ride-骑行系列，general-综合成就
    
    @Column(name = "target", nullable = false)
    private Integer target; // 解锁目标值
    
    @Column(name = "stat_key", nullable = false, length = 50)
    private String statKey; // 统计字段名（对应user表的字段）
    
    @Column(name = "description", length = 200)
    private String description; // 描述
    
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

