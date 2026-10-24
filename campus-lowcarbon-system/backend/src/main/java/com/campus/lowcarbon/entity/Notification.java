/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 通知消息实体类
 * 对应数据库表：notification
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "notification")
@Data
public class Notification {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "sender_id")
    private Long senderId; // 发送者ID（管理员），NULL表示系统自动发送
    
    @Column(name = "receiver_id", nullable = false)
    private Long receiverId; // 接收者ID（用户或管理员）
    
    @Column(name = "type", nullable = false, length = 20)
    private String type; // 通知类型：REJECT-驳回通知，SYSTEM-系统通知，REVIEW-人工复核通知，MAIL-管理员邮件
    
    @Column(name = "title", nullable = false, length = 200)
    private String title; // 通知标题
    
    @Column(name = "content", columnDefinition = "TEXT")
    private String content; // 通知内容
    
    @Column(name = "is_read")
    private Integer isRead = 0; // 是否已读：1-已读，0-未读
    
    @Column(name = "related_type", length = 20)
    private String relatedType; // 关联类型：CHECKIN-打卡记录，REVIEW-审核记录
    
    @Column(name = "related_id")
    private Long relatedId; // 关联ID（如打卡记录ID、审核记录ID）
    
    @Column(name = "extra_data", columnDefinition = "TEXT")
    private String extraData; // 额外数据（JSON格式，存储关联信息）
    
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 创建时间
    
    @Column(name = "read_at")
    private LocalDateTime readAt; // 阅读时间
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}

