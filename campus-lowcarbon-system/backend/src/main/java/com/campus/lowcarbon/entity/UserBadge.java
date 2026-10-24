/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户勋章关联实体类
 * 对应数据库表：user_badge
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "user_badge", uniqueConstraints = {
    @UniqueConstraint(columnNames = {"user_id", "badge_id"})
})
@Data
public class UserBadge {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "user_id", nullable = false)
    private Long userId; // 用户ID
    
    @Column(name = "badge_id", nullable = false)
    private Long badgeId; // 勋章ID
    
    @Column(name = "is_equipped")
    private Integer isEquipped = 0; // 是否佩戴：1-是，0-否
    
    @Column(name = "is_displayed")
    private Integer isDisplayed = 0; // 是否在排行榜展示：1-是，0-否
    
    @Column(name = "unlock_time")
    private LocalDateTime unlockTime; // 解锁时间
    
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 创建时间
    
    @Column(name = "updated_at")
    private LocalDateTime updatedAt; // 更新时间
    
    // 关联实体
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", insertable = false, updatable = false)
    private User user;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "badge_id", insertable = false, updatable = false)
    private Badge badge;
    
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

