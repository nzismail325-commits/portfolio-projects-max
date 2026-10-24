/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import java.util.List;

/**
 * 首页数据传输对象
 * 
 * @author Campus Team
 */
@Data
public class DashboardDTO {
    
    /**
     * 首页数据
     */
    @Data
    public static class DashboardData {
        private UserInfo userInfo; // 用户信息
        private TipsData tipsData; // 低碳贴士数据
        private List<TodayRecord> todayRecords; // 今日打卡记录
    }
    
    /**
     * 用户信息
     */
    @Data
    public static class UserInfo {
        private Integer points; // 积分
        private Integer totalCheckins; // 总打卡次数
    }
    
    /**
     * 低碳贴士数据
     * 注意：AI生成的每日贴士由前端直接调用AI服务获取，不在此DTO中
     */
    @Data
    public static class TipsData {
        private Double savedElectricity; // 累计节电(度)
        private Double carbonReduction; // 减碳量(kg)
        private Integer points; // 我的积分
    }
    
    /**
     * 今日打卡记录
     */
    @Data
    public static class TodayRecord {
        private Long id; // 记录ID
        private String name; // 场景名称
        private String icon; // 图标
        private String time; // 提交时间（格式：HH:mm）
        private String status; // 状态：success-已通过，pending-审核中
        private Integer points; // 奖励积分
    }
    
    /**
     * 管理员看板数据
     */
    @Data
    public static class AdminDashboardData {
        private List<StatCard> stats; // KPI统计卡片
        private List<PendingReview> pendingReviews; // 待审核记录列表
        private List<AlertItem> alerts; // 异常报警列表
    }
    
    /**
     * KPI统计卡片
     */
    @Data
    public static class StatCard {
        private String title; // 标题
        private String value; // 数值（格式化后的字符串）
        private String trend; // 趋势（如：+12.5%、-5.2%）
        private Boolean trendUp; // 趋势是否上升
        private Boolean clickable; // 是否可点击
    }
    
    /**
     * 待审核记录
     */
    @Data
    public static class PendingReview {
        private Long id; // 记录ID
        private Long checkinId; // 打卡记录ID
        private String name; // 用户姓名
        private String scene; // 场景名称
        private String sceneType; // 场景类型
        private String time; // 提交时间（相对时间，如：10分钟前）
        private String imageUrl; // 图片URL
    }
    
    /**
     * 异常报警项
     */
    @Data
    public static class AlertItem {
        private Long id; // 记录ID
        private String title; // 异常标题
        private String desc; // 异常描述
        private String time; // 提交时间（相对时间，如：5分钟前）
        private String reasonType; // 原因类型：warning-警告，danger-危险，info-信息
        private Integer confidence; // AI异常置信度（0-100）
    }
    
    /**
     * 场景参与占比数据（用于饼图）
     */
    @Data
    public static class SceneParticipationData {
        private String sceneType; // 场景类型
        private String sceneName; // 场景名称
        private Integer count; // 参与次数
        private Double percentage; // 占比百分比
    }
    
    /**
     * 活跃度数据（用于折线图）
     */
    @Data
    public static class ActivityData {
        private String date; // 日期（格式：MM-dd）
        private Integer activeUsers; // 活跃用户数
        private Integer checkinCount; // 打卡次数
    }
    
    /**
     * 场景参与占比分析结果（后端计算）
     */
    @Data
    public static class SceneParticipationAnalysis {
        private String analysis; // 分析文本
        private List<String> insights; // 关键洞察
        private List<String> recommendations; // 改进建议
        private String source; // 来源：ai-AI分析，backend-后端计算
    }
    
    /**
     * 活跃度趋势分析结果（后端计算）
     */
    @Data
    public static class ActivityTrendAnalysis {
        private String analysis; // 分析文本
        private String trend; // 趋势：上升/下降/平稳
        private String peakDay; // 峰值日期
        private List<String> insights; // 关键洞察
        private String source; // 来源：ai-AI分析，backend-后端计算
    }
    
    /**
     * 个人统计数据
     */
    @Data
    public static class PersonalStatsData {
        private List<PersonalCheckinTrend> checkinTrend; // 近7天/30天打卡趋势
        private List<PersonalSceneDistribution> sceneDistribution; // 各场景打卡分布
        private PersonalCarbonStats carbonStats; // 减碳量统计
        private PersonalPointsTrend pointsTrend; // 积分获取趋势
    }
    
    /**
     * 个人打卡趋势数据
     */
    @Data
    public static class PersonalCheckinTrend {
        private String date; // 日期（格式：MM-dd）
        private Integer count; // 打卡次数
    }
    
    /**
     * 个人场景分布数据
     */
    @Data
    public static class PersonalSceneDistribution {
        private String sceneType; // 场景类型
        private String sceneName; // 场景名称
        private String icon; // 图标
        private Integer count; // 打卡次数
        private Double percentage; // 占比百分比
    }
    
    /**
     * 个人减碳量统计
     */
    @Data
    public static class PersonalCarbonStats {
        private Double totalCarbonReduction; // 累计减碳量(kg)
        private Double monthlyCarbonReduction; // 本月减碳量(kg)
        private Double weeklyCarbonReduction; // 本周减碳量(kg)
    }
    
    /**
     * 个人积分获取趋势
     */
    @Data
    public static class PersonalPointsTrend {
        private List<PersonalCheckinTrend> dailyPoints; // 每日积分获取（近7天）
        private Integer totalPoints; // 总积分
        private Integer monthlyPoints; // 本月积分
        private Integer weeklyPoints; // 本周积分
    }
    
    /**
     * 个人数据分析结果（AI分析）
     */
    @Data
    public static class PersonalDataAnalysis {
        private String analysis; // 分析文本
        private List<String> insights; // 关键洞察
        private List<String> recommendations; // 改进建议
        private String source; // 来源：ai-AI分析，backend-后端计算
    }
    
    /**
     * 个人数据计算分析结果（后端计算，用于AI分析）
     */
    @Data
    public static class PersonalDataCalculation {
        private CheckinTrendAnalysis checkinTrendAnalysis; // 打卡趋势分析
        private SceneDistributionAnalysis sceneDistributionAnalysis; // 场景分布分析
        private CarbonReductionAnalysis carbonReductionAnalysis; // 减碳量分析
        private PointsAnalysis pointsAnalysis; // 积分分析
        private OverallAssessment overallAssessment; // 综合评估
    }
    
    /**
     * 打卡趋势分析
     */
    @Data
    public static class CheckinTrendAnalysis {
        private Double averageDailyCheckins; // 平均每日打卡次数
        private Integer maxDailyCheckins; // 单日最高打卡次数
        private Integer minDailyCheckins; // 单日最低打卡次数
        private String trend; // 趋势：上升/下降/平稳
        private Double trendRate; // 趋势变化率（百分比）
        private Integer consecutiveDays; // 连续打卡天数
        private Integer activeDays; // 活跃天数（有打卡的天数）
        private String consistency; // 一致性评价：优秀/良好/一般/需改进
    }
    
    /**
     * 场景分布分析
     */
    @Data
    public static class SceneDistributionAnalysis {
        private String favoriteScene; // 最偏好的场景
        private Double favoriteScenePercentage; // 最偏好场景占比
        private String leastFavoriteScene; // 最少参与的场景
        private Double leastFavoriteScenePercentage; // 最少参与场景占比
        private Double diversityScore; // 多样性得分（0-100）
        private String diversityLevel; // 多样性等级：高/中/低
        private List<String> missingScenes; // 未参与的场景列表
    }
    
    /**
     * 减碳量分析
     */
    @Data
    public static class CarbonReductionAnalysis {
        private Double totalCarbonReduction; // 累计减碳量
        private Double averageDailyCarbonReduction; // 平均每日减碳量
        private Double monthlyCarbonReduction; // 本月减碳量
        private Double weeklyCarbonReduction; // 本周减碳量
        private Double monthlyGrowthRate; // 月度增长率
        private Double weeklyGrowthRate; // 周增长率
        private String contributionLevel; // 贡献等级：卓越/优秀/良好/一般
        private String equivalentDescription; // 等价描述（如：相当于种植X棵树）
    }
    
    /**
     * 积分分析
     */
    @Data
    public static class PointsAnalysis {
        private Integer totalPoints; // 总积分
        private Integer monthlyPoints; // 本月积分
        private Integer weeklyPoints; // 本周积分
        private Double averageDailyPoints; // 平均每日积分
        private Integer maxDailyPoints; // 单日最高积分
        private Double monthlyGrowthRate; // 月度增长率
        private Double weeklyGrowthRate; // 周增长率
        private String activityLevel; // 活跃度等级：极高/高/中/低
    }
    
    /**
     * 综合评估
     */
    @Data
    public static class OverallAssessment {
        private String overallLevel; // 综合等级：优秀/良好/一般/需改进
        private Integer overallScore; // 综合得分（0-100）
        private List<String> strengths; // 优势点
        private List<String> weaknesses; // 待改进点
        private String summary; // 总结评价
    }
}

