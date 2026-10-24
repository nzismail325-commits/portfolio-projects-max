/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 审核记录实体类
 * 对应数据库表：review_record
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "review_record")
@Data
public class ReviewRecord {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "checkin_id", nullable = false)
    private Long checkinId; // 打卡记录ID
    
    @Column(name = "user_id", nullable = false)
    private Long userId; // 用户ID
    
    @Column(name = "scene_type", nullable = false, length = 20)
    private String sceneType; // 场景类型
    
    @Column(name = "image_url", length = 255)
    private String imageUrl; // 凭证图片URL
    
    @Column(name = "reason", length = 200)
    private String reason; // 异常原因
    
    @Column(name = "reason_type", length = 20)
    private String reasonType; // 原因类型：warning-警告，danger-危险，info-信息
    
    @Column(name = "confidence")
    private Integer confidence; // AI异常置信度（0-100）
    
    @Column(name = "ai_reason", columnDefinition = "TEXT")
    private String aiReason; // AI详细原因说明
    
    @Column(name = "review_status", length = 20)
    private String reviewStatus = "PENDING"; // 审核状态：PENDING-待处理，APPROVED-已通过，REJECTED-已驳回
    
    @Column(name = "reviewer_id")
    private Long reviewerId; // 审核人ID（管理员）
    
    @Column(name = "review_comment", columnDefinition = "TEXT")
    private String reviewComment; // 审核意见
    
    @Column(name = "submit_time")
    private LocalDateTime submitTime; // 提交时间
    
    @Column(name = "review_time")
    private LocalDateTime reviewTime; // 审核时间
    
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 创建时间
    
    @Column(name = "updated_at")
    private LocalDateTime updatedAt; // 更新时间
    
    @PrePersist
    protected void onCreate() {
        if (submitTime == null) {
            submitTime = LocalDateTime.now();
        }
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }
    
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}

