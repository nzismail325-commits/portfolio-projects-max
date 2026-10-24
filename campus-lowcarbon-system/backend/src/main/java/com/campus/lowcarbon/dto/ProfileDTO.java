/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import java.util.List;

/**
 * 我的荣誉页面数据传输对象
 * 
 * @author Campus Team
 */
@Data
public class ProfileDTO {
    
    /**
     * 我的荣誉页面数据
     */
    @Data
    public static class ProfileData {
        private UserProfile userProfile; // 用户资料
        private List<TitleInfo> titles; // 已拥有的称号列表
        private List<BadgeInfo> badges; // 已拥有的勋章列表
    }
    
    /**
     * 用户资料
     */
    @Data
    public static class UserProfile {
        private String name; // 用户名
        private String nickname; // 昵称
        private String studentId; // 学号
        private String avatar; // 头像URL
        private Integer points; // 积分
        private Integer totalCheckins; // 总打卡次数
        private Double carbonReduction; // 累计减碳量（kg）
        private Integer rankPercentage; // 超过全校百分比（0-100）
    }
    
    /**
     * 称号信息
     */
    @Data
    public static class TitleInfo {
        private Long id; // 称号ID
        private String name; // 称号名称
        private String icon; // 图标
        private Integer level; // 等级（0-未解锁，1-5为等级）
        private Boolean isEquipped; // 是否佩戴
    }
    
    /**
     * 勋章信息
     */
    @Data
    public static class BadgeInfo {
        private Long id; // 勋章ID
        private String name; // 勋章名称
        private String icon; // 图标
        private String type; // 类型
        private Boolean isEquipped; // 是否佩戴
    }
}

