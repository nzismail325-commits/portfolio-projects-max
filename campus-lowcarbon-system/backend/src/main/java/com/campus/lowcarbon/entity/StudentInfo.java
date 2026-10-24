/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 学生学号信息实体类
 * 对应数据库表：student_info
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "student_info")
@Data
public class StudentInfo {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "student_id", unique = true, nullable = false, length = 20)
    private String studentId; // 学号
    
    @Column(name = "name", nullable = false, length = 50)
    private String name; // 真实姓名（用于注册验证）
    
    @Column(name = "college", length = 100)
    private String college; // 学院（管理员风控页面显示）
    
    @Column(name = "class_name", length = 50)
    private String className; // 班级（管理员风控页面显示）
    
    @Column(name = "status")
    private Integer status = 1; // 状态：1-有效，0-无效
    
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

