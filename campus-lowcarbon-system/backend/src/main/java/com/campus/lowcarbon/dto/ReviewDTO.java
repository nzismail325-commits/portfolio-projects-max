/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 异常审核DTO
 * 
 * @author Campus Team
 */
public class ReviewDTO {
    
    /**
     * 审核记录信息
     */
    @Data
    public static class ReviewRecordInfo {
        private Long id; // 审核记录ID
        private Long checkinId; // 打卡记录ID
        private Long userId; // 用户ID
        private String name; // 用户姓名
        private String studentId; // 学号
        private String avatar; // 头像URL
        private String avatarBg; // 头像背景色（前端计算）
        private String sceneType; // 场景类型
        private String scene; // 场景名称（中文）
        private String sceneIcon; // 场景图标
        private String imageUrl; // 凭证图片URL
        private String evidence; // 凭证图片URL（别名，与前端保持一致）
        private String reason; // 异常原因
        private String reasonIcon; // 原因图标（前端计算）
        private String reasonType; // 原因类型：warning-警告，danger-危险，info-信息
        private Integer confidence; // AI异常置信度（0-100）
        private String aiReason; // AI详细原因说明
        private String submitDate; // 提交日期（格式：yyyy-MM-dd）
        private String submitTime; // 提交时间（格式：HH:mm:ss）
        private LocalDateTime submitDateTime; // 提交时间（完整）
    }
    
    /**
     * 审核统计信息
     */
    @Data
    public static class ReviewStatistics {
        private Long pendingCount; // 待处理异常数量
        private Long todayRejectedCount; // 今日自动驳回数量
        private Long todayApprovedCount; // 今日人工复核通过数量
        private Long todayAiApprovedCount; // 今日AI自动通过数量
    }
    
    /**
     * 审核列表响应
     */
    @Data
    public static class ReviewListResponse {
        private List<ReviewRecordInfo> records; // 审核记录列表
        private ReviewStatistics statistics; // 统计数据
        private Long total; // 总记录数
        private Integer page; // 当前页码
        private Integer pageSize; // 每页大小
    }
    
    /**
     * 审核操作请求
     */
    @Data
    public static class ReviewActionRequest {
        private Long reviewId; // 审核记录ID
        private String action; // 操作类型：APPROVE-通过，REJECT-驳回
        private String comment; // 审核意见（驳回时必填）
        private Double extractedValue; // 提取的数值（步数/里程，仅walk和ride类型需要，可选）
    }
    
    /**
     * 审核操作响应
     */
    @Data
    public static class ReviewActionResponse {
        private Long reviewId; // 审核记录ID
        private String action; // 操作类型
        private String message; // 操作结果消息
    }
}

