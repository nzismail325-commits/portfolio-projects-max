/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 打卡记录实体类
 * 对应数据库表：checkin_record
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "checkin_record")
@Data
public class CheckinRecord {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "user_id", nullable = false)
    private Long userId; // 用户ID
    
    @Column(name = "scene_type", nullable = false, length = 20)
    private String sceneType; // 场景类型：walk-健步走，ride-骑行，plate-光盘，transit-公共交通
    
    @Column(name = "image_url", length = 255)
    private String imageUrl; // 凭证图片URL
    
    @Column(name = "image_hash", length = 64)
    private String imageHash; // 图片MD5哈希值（用于重复检测）
    
    @Column(name = "status", length = 20)
    private String status = "PENDING"; // 状态：PENDING-待审核，APPROVED-已通过，REJECTED-已驳回，SUSPICIOUS-可疑
    
    @Column(name = "reward_points")
    private Integer rewardPoints = 0; // 奖励积分
    
    @Column(name = "verify_reason", columnDefinition = "TEXT")
    private String verifyReason; // 验证原因/拒绝原因
    
    @Column(name = "verify_steps", columnDefinition = "JSON")
    private String verifySteps; // 验证步骤详情（JSON数组字符串）
    
    @Column(name = "submit_time")
    private LocalDateTime submitTime; // 提交时间
    
    @Column(name = "verify_time")
    private LocalDateTime verifyTime; // 审核时间
    
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

