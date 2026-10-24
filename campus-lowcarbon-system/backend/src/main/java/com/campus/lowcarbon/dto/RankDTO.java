/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;

/**
 * 排行榜数据传输对象
 * 
 * @author Campus Team
 */
@Data
public class RankDTO {
    
    private Long userId; // 用户ID
    private String name; // 显示名称（昵称或真实姓名，根据权限决定）
    private String nickname; // 昵称
    private String realName; // 真实姓名
    private String studentId; // 学号（仅管理员可见）
    private String avatar; // 头像URL
    private Integer points; // 积分
    private Integer badgesCount; // 勋章数量
    private Integer checkins; // 打卡次数
    private Integer titleScore; // 称号分数
    private FeaturedItem featuredItem; // 展示的称号或勋章
    private String trend; // 趋势：up/down/stable
    private Boolean isCurrentUser; // 是否为当前用户
    
    /**
     * 展示项（称号或勋章）
     */
    @Data
    public static class FeaturedItem {
        private String name; // 名称
        private String icon; // 图标
        private Integer level; // 等级（称号用）
    }
}

