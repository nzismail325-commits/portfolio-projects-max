/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户实体类
 * 对应数据库表：user
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "user")
@Data
public class User {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "student_id", unique = true, nullable = false, length = 20)
    private String studentId; // 学号/管理员账号
    
    @Column(name = "username", nullable = false, length = 50)
    private String username; // 用户名（姓名）
    
    @Column(name = "password", nullable = false, length = 100)
    private String password; // 密码（明文存储）
    
    @Column(name = "role", nullable = false, length = 20)
    private String role = "student"; // 角色：student-学生，admin-管理员
    
    @Column(name = "avatar", length = 255)
    private String avatar; // 头像URL
    
    @Column(name = "nickname", length = 50)
    private String nickname; // 昵称
    
    @Column(name = "signature", length = 200)
    private String signature; // 个性签名
    
    @Column(name = "last_login_time")
    private LocalDateTime lastLoginTime; // 最近登录时间
    
    @Column(name = "status")
    private Integer status = 1; // 账号状态：1-正常，0-封禁
    
    // 积分字段
    @Column(name = "points")
    private Integer points = 0; // 积分数量
    
    // 统计字段
    @Column(name = "walk_checkins")
    private Integer walkCheckins = 0; // 健步走打卡次数
    
    @Column(name = "plate_checkins")
    private Integer plateCheckins = 0; // 光盘行动打卡次数
    
    @Column(name = "ride_checkins")
    private Integer rideCheckins = 0; // 骑行打卡次数
    
    @Column(name = "transit_checkins")
    private Integer transitCheckins = 0; // 公共交通打卡次数
    
    @Column(name = "total_checkins")
    private Integer totalCheckins = 0; // 总打卡次数
    
    // 风控字段
    @Column(name = "suspicious_count")
    private Integer suspiciousCount = 0; // 异常次数
    
    @Column(name = "risk_level", length = 20)
    private String riskLevel = "SAFE"; // 风险等级：SAFE-安全，SUSPICIOUS-存疑，HIGH-高危
    
    @Column(name = "ban_reason", columnDefinition = "TEXT")
    private String banReason; // 封禁原因
    
    @Column(name = "ban_time")
    private LocalDateTime banTime; // 封禁时间
    
    @Column(name = "token_version")
    private Long tokenVersion = 0L; // Token版本号（用于强制退出登录）
    
    // 支付密码字段（仅学生使用）
    @Column(name = "payment_password", length = 6)
    private String paymentPassword; // 支付密码（6位数字，明文存储）
    
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

