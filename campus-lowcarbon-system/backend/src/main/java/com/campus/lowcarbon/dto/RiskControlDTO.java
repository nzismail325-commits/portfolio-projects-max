/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;

import java.util.List;

/**
 * 用户风控DTO
 * 
 * @author Campus Team
 */
public class RiskControlDTO {
    
    /**
     * 用户风控信息响应
     */
    @Data
    public static class UserRiskInfo {
        private Long id; // 用户ID
        private String name; // 姓名（username或nickname）
        private String studentId; // 学号
        private String avatar; // 头像URL
        private String college; // 学院
        private String className; // 班级
        private Integer suspiciousCount; // 异常次数
        private String riskLevel; // 风险等级：SAFE-安全，SUSPICIOUS-存疑，HIGH-高危
        private String status; // 账号状态：normal-正常，banned-已封禁
        private String banReason; // 封禁原因
        private String banTime; // 封禁时间
    }
    
    /**
     * 用户风控列表响应
     */
    @Data
    public static class UserRiskListResponse {
        private List<UserRiskInfo> users; // 用户列表
        private RiskStatistics statistics; // 统计数据
    }
    
    /**
     * 统计数据
     */
    @Data
    public static class RiskStatistics {
        private Integer highRiskCount; // 高危用户数（suspiciousCount >= 5）
        private Integer suspiciousCount; // 存疑用户数（0 < suspiciousCount < 5）
        private Integer bannedCount; // 已封禁用户数
    }
    
    /**
     * 封禁用户请求
     */
    @Data
    public static class BanUserRequest {
        private Long userId; // 用户ID
        private String reason; // 封禁原因
    }
    
    /**
     * 解封用户请求
     */
    @Data
    public static class UnbanUserRequest {
        private Long userId; // 用户ID
    }
}

