/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import java.util.List;

/**
 * 商城数据传输对象
 * 
 * @author Campus Team
 */
@Data
public class MallDTO {
    
    /**
     * 用户资产信息
     */
    @Data
    public static class UserAssets {
        private Integer points; // 积分
        private Integer unlockedTitlesCount; // 已解锁称号数量
        private Integer maxTitleLevel; // 最高称号等级
        private Integer ownedBadgesCount; // 已拥有勋章数量
        private Integer totalCheckins; // 总打卡次数
    }
    
    /**
     * 称号信息
     */
    @Data
    public static class TitleInfo {
        private Long id; // 称号ID
        private String name; // 称号名称
        private String icon; // 图标
        private Integer baseCost; // 基础解锁费用
        private Integer maxLevel; // 最大等级
        private Integer level; // 当前等级（0-未解锁，1-5为等级）
        private Boolean isOwned; // 是否已拥有
        private Boolean isEquipped; // 是否佩戴
        private Integer nextUpgradeCost; // 下一级升级费用
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
        private Integer target; // 解锁目标值
        private String statKey; // 统计字段名
        private String description; // 描述
        private Boolean isOwned; // 是否已拥有
        private Boolean isEquipped; // 是否佩戴
        private Integer currentProgress; // 当前进度
        private Integer progressPercentage; // 进度百分比
    }
    
    /**
     * 用户统计数据
     */
    @Data
    public static class UserStats {
        private Integer walkCheckins; // 健步走打卡次数
        private Integer plateCheckins; // 光盘行动打卡次数
        private Integer rideCheckins; // 骑行打卡次数
        private Integer transitCheckins; // 公共交通打卡次数
        private Integer totalCheckins; // 总打卡次数
    }
}

