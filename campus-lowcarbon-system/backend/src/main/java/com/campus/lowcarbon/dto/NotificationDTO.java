/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 通知消息DTO
 * 
 * @author Campus Team
 */
public class NotificationDTO {
    
    /**
     * 获取未读数量响应
     */
    @Data
    public static class UnreadCountResponse {
        private Long unreadCount; // 未读数量
    }
    
    /**
     * 获取消息列表请求
     */
    @Data
    public static class ListRequest {
        private Integer page = 1; // 页码
        private Integer pageSize = 20; // 每页大小
        private String type; // 通知类型筛选（可选）
        private Integer isRead; // 是否已读筛选（0-未读，1-已读，不传则全部）
    }
    
    /**
     * 通知消息信息
     */
    @Data
    public static class NotificationInfo {
        private Long id; // 通知ID
        private String type; // 通知类型
        private String title; // 通知标题
        private String content; // 通知内容
        private Boolean isRead; // 是否已读
        private String senderName; // 发送者姓名（如果有）
        private LocalDateTime createdAt; // 创建时间
        private Map<String, Object> extraData; // 额外数据
    }
    
    /**
     * 获取消息列表响应
     */
    @Data
    public static class ListResponse {
        private List<NotificationInfo> records; // 通知列表
        private Long total; // 总数量
        private Integer page; // 当前页码
        private Integer pageSize; // 每页大小
        private Long unreadCount; // 未读数量
    }
    
    /**
     * 标记已读请求
     */
    @Data
    public static class MarkReadRequest {
        private Long notificationId; // 通知ID
    }
    
    /**
     * 发送邮件请求
     */
    @Data
    public static class SendMailRequest {
        private String sendType; // 发送类型：SINGLE-单个，BATCH-批量，GRADE-按年级，CLASS-按班级
        private List<Long> receiverIds; // 收件人ID列表（SINGLE和BATCH时使用）
        private String filterValue; // 筛选值（GRADE和CLASS时使用，如"2021"或"计算机1班"）
        private String title; // 邮件主题
        private String content; // 邮件内容
    }
    
    /**
     * 发送邮件响应
     */
    @Data
    public static class SendMailResponse {
        private Integer successCount; // 成功发送数量
        private Integer failCount; // 失败数量
        private String message; // 响应消息
    }
    
    /**
     * 学生信息（用于选择收件人）
     */
    @Data
    public static class StudentInfo {
        private Long id; // 用户ID
        private String name; // 姓名
        private String studentId; // 学号
        private String className; // 班级
        private String college; // 学院
    }
    
    /**
     * 获取学生列表请求
     */
    @Data
    public static class StudentListRequest {
        private String keyword; // 搜索关键词（姓名或学号）
        private String grade; // 年级筛选（如"2021"）
        private String className; // 班级筛选
    }
    
    /**
     * 年级信息
     */
    @Data
    public static class GradeInfo {
        private String grade; // 年级（如"2021"）
        private String displayName; // 显示名称（如"2021级"）
    }
    
    /**
     * 班级信息（包含年级）
     */
    @Data
    public static class ClassInfo {
        private String className; // 班级名称
        private String grade; // 年级（如"2021"）
        private String displayName; // 显示名称（如"2021级-计算机1班"）
    }
    
    /**
     * 获取年级列表响应
     */
    @Data
    public static class GradeListResponse {
        private List<GradeInfo> grades; // 年级列表
    }
    
    /**
     * 获取班级列表响应
     */
    @Data
    public static class ClassListResponse {
        private List<ClassInfo> classes; // 班级列表
    }
}

