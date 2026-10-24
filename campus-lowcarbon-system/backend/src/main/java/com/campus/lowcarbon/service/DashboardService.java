/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.DashboardDTO;
import com.campus.lowcarbon.entity.CheckinRecord;
import com.campus.lowcarbon.entity.ReviewRecord;
import com.campus.lowcarbon.entity.SceneConfig;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.CheckinRecordRepository;
import com.campus.lowcarbon.repository.ReviewRecordRepository;
import com.campus.lowcarbon.repository.SceneConfigRepository;
import com.campus.lowcarbon.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 首页服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class DashboardService {
    
    private final UserRepository userRepository;
    private final CheckinRecordRepository checkinRecordRepository;
    private final ReviewRecordRepository reviewRecordRepository;
    private final SceneConfigRepository sceneConfigRepository;
    
    /**
     * 获取首页数据
     * 
     * @param userId 用户ID
     * @return 首页数据
     */
    public DashboardDTO.DashboardData getDashboardData(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        DashboardDTO.DashboardData data = new DashboardDTO.DashboardData();
        
        // 用户信息
        DashboardDTO.UserInfo userInfo = new DashboardDTO.UserInfo();
        userInfo.setPoints(user.getPoints() != null ? user.getPoints() : 0);
        userInfo.setTotalCheckins(user.getTotalCheckins() != null ? user.getTotalCheckins() : 0);
        data.setUserInfo(userInfo);
        
        // 低碳贴士数据（根据用户各场景打卡次数和对应减碳量动态计算）
        DashboardDTO.TipsData tipsData = new DashboardDTO.TipsData();
        
        // 获取所有场景配置
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        // 计算累计减碳量
        BigDecimal totalCarbonReduction = BigDecimal.ZERO;
        int totalCheckins = user.getTotalCheckins() != null ? user.getTotalCheckins() : 0;
        
        // 健步走减碳量
        int walkCheckins = user.getWalkCheckins() != null ? user.getWalkCheckins() : 0;
        SceneConfig walkConfig = sceneConfigMap.get("walk");
        if (walkConfig != null && walkConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                walkConfig.getCarbonReduction().multiply(new BigDecimal(walkCheckins))
            );
        }
        
        // 骑行减碳量
        int rideCheckins = user.getRideCheckins() != null ? user.getRideCheckins() : 0;
        SceneConfig rideConfig = sceneConfigMap.get("ride");
        if (rideConfig != null && rideConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                rideConfig.getCarbonReduction().multiply(new BigDecimal(rideCheckins))
            );
        }
        
        // 光盘行动减碳量
        int plateCheckins = user.getPlateCheckins() != null ? user.getPlateCheckins() : 0;
        SceneConfig plateConfig = sceneConfigMap.get("plate");
        if (plateConfig != null && plateConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                plateConfig.getCarbonReduction().multiply(new BigDecimal(plateCheckins))
            );
        }
        
        // 公共交通减碳量
        int transitCheckins = user.getTransitCheckins() != null ? user.getTransitCheckins() : 0;
        SceneConfig transitConfig = sceneConfigMap.get("transit");
        if (transitConfig != null && transitConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                transitConfig.getCarbonReduction().multiply(new BigDecimal(transitCheckins))
            );
        }

        tipsData.setSavedElectricity(totalCheckins * 0.5);
        tipsData.setCarbonReduction(totalCarbonReduction.doubleValue());
        tipsData.setPoints(user.getPoints() != null ? user.getPoints() : 0);

        data.setTipsData(tipsData);
        
        // 今日打卡记录
        LocalDate today = LocalDate.now();
        LocalDateTime startTime = today.atStartOfDay();
        LocalDateTime endTime = today.atTime(LocalTime.MAX);
        
        List<CheckinRecord> todayRecords = checkinRecordRepository.findTodayRecords(userId, startTime, endTime);
        
        // 过滤出成功打卡的记录（只显示APPROVED状态的记录）
        List<CheckinRecord> approvedRecords = todayRecords.stream()
                .filter(r -> "APPROVED".equals(r.getStatus()))
                .collect(Collectors.toList());
        
        // 使用之前已获取的场景配置映射，用于映射场景名称和图标
        List<DashboardDTO.TodayRecord> recordList = approvedRecords.stream().map(record -> {
            DashboardDTO.TodayRecord dto = new DashboardDTO.TodayRecord();
            dto.setId(record.getId());
            
            // 从场景配置中获取名称和图标
            SceneConfig config = sceneConfigMap.get(record.getSceneType());
            if (config != null) {
                dto.setName(config.getTitle());
                dto.setIcon(config.getIcon());
            } else {
                // 如果没有配置，使用默认值
                dto.setName(getDefaultSceneName(record.getSceneType()));
                dto.setIcon(getDefaultSceneIcon(record.getSceneType()));
            }
            
            // 格式化时间
            if (record.getSubmitTime() != null) {
                dto.setTime(record.getSubmitTime().format(DateTimeFormatter.ofPattern("HH:mm")));
            } else {
                dto.setTime("--:--");
            }
            
            // 状态映射
            if ("APPROVED".equals(record.getStatus())) {
                dto.setStatus("success");
            } else {
                dto.setStatus("pending");
            }
            
            dto.setPoints(record.getRewardPoints() != null ? record.getRewardPoints() : 0);
            
            return dto;
        }).collect(Collectors.toList());
        
        data.setTodayRecords(recordList);
        
        return data;
    }
    
    /**
     * 获取默认场景名称
     */
    private String getDefaultSceneName(String sceneType) {
        switch (sceneType) {
            case "walk":
                return "低碳健步走";
            case "ride":
                return "绿色骑行";
            case "plate":
                return "光盘行动";
            case "transit":
                return "公共交通";
            default:
                return "未知场景";
        }
    }
    
    /**
     * 获取默认场景图标
     */
    private String getDefaultSceneIcon(String sceneType) {
        switch (sceneType) {
            case "walk":
                return "🏃";
            case "ride":
                return "🚲";
            case "plate":
                return "🍽️";
            case "transit":
                return "🚌";
            default:
                return "📋";
        }
    }
    
    /**
     * 获取管理员看板数据
     * 
     * @return 管理员看板数据
     */
    public DashboardDTO.AdminDashboardData getAdminDashboardData() {
        DashboardDTO.AdminDashboardData data = new DashboardDTO.AdminDashboardData();
        
        // 1. 获取KPI统计数据
        data.setStats(getAdminStats());
        
        // 2. 获取待审核记录列表（最多10条）
        data.setPendingReviews(getPendingReviews(10));
        
        // 3. 获取异常报警列表（最多10条）
        data.setAlerts(getAlerts(10));
        
        return data;
    }
    
    /**
     * 获取KPI统计数据
     */
    private List<DashboardDTO.StatCard> getAdminStats() {
        List<DashboardDTO.StatCard> stats = new ArrayList<>();
        
        LocalDate today = LocalDate.now();
        LocalDateTime todayStart = today.atStartOfDay();
        LocalDateTime todayEnd = today.atTime(LocalTime.MAX);
        
        LocalDate yesterday = today.minusDays(1);
        LocalDateTime yesterdayStart = yesterday.atStartOfDay();
        LocalDateTime yesterdayEnd = yesterday.atTime(LocalTime.MAX);
        
        // 1. 今日活跃人数（只统计成功打卡的用户）
        long todayActiveUsers = checkinRecordRepository.findAll().stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(todayStart) && 
                        r.getSubmitTime().isBefore(todayEnd) &&
                        "APPROVED".equals(r.getStatus()))
                .map(CheckinRecord::getUserId)
                .distinct()
                .count();
        
        long yesterdayActiveUsers = checkinRecordRepository.findAll().stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(yesterdayStart) && 
                        r.getSubmitTime().isBefore(yesterdayEnd) &&
                        "APPROVED".equals(r.getStatus()))
                .map(CheckinRecord::getUserId)
                .distinct()
                .count();
        
        DashboardDTO.StatCard activeUsersCard = new DashboardDTO.StatCard();
        activeUsersCard.setTitle("今日活跃人数");
        activeUsersCard.setValue(formatNumber(todayActiveUsers));
        activeUsersCard.setTrend(calculateTrend(todayActiveUsers, yesterdayActiveUsers, true));
        activeUsersCard.setTrendUp(todayActiveUsers >= yesterdayActiveUsers);
        activeUsersCard.setClickable(false);
        stats.add(activeUsersCard);
        
        // 2. 累计减碳量（kg）
        // 假设每次打卡平均减少0.3925kg二氧化碳
        long totalApprovedCheckins = checkinRecordRepository.findAll().stream()
                .filter(r -> "APPROVED".equals(r.getStatus()))
                .count();
        double totalCarbonReduction = totalApprovedCheckins * 0.3925;
        
        // 计算昨天的累计减碳量（用于趋势）
        long yesterdayApprovedCheckins = checkinRecordRepository.findAll().stream()
                .filter(r -> "APPROVED".equals(r.getStatus()) && 
                        r.getSubmitTime() != null && 
                        r.getSubmitTime().isBefore(todayStart))
                .count();
        double yesterdayCarbonReduction = yesterdayApprovedCheckins * 0.3925;
        
        DashboardDTO.StatCard carbonCard = new DashboardDTO.StatCard();
        carbonCard.setTitle("累计减碳量(kg)");
        carbonCard.setValue(formatNumber((long) totalCarbonReduction));
        carbonCard.setTrend(calculateTrend(totalCarbonReduction, yesterdayCarbonReduction, false));
        carbonCard.setTrendUp(totalCarbonReduction >= yesterdayCarbonReduction);
        carbonCard.setClickable(false);
        stats.add(carbonCard);
        
        // 3. 今日打卡次数（只统计成功打卡的记录）
        long todayCheckinCount = checkinRecordRepository.findAll().stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(todayStart) && 
                        r.getSubmitTime().isBefore(todayEnd) &&
                        "APPROVED".equals(r.getStatus()))
                .count();
        
        // 计算昨天的打卡次数（只统计成功打卡的记录）
        long yesterdayCheckinCount = checkinRecordRepository.findAll().stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(yesterdayStart) && 
                        r.getSubmitTime().isBefore(yesterdayEnd) &&
                        "APPROVED".equals(r.getStatus()))
                .count();
        
        DashboardDTO.StatCard checkinCard = new DashboardDTO.StatCard();
        checkinCard.setTitle("今日打卡次数");
        checkinCard.setValue(formatNumber(todayCheckinCount));
        checkinCard.setTrend(calculateTrend(todayCheckinCount, yesterdayCheckinCount, true));
        checkinCard.setTrendUp(todayCheckinCount >= yesterdayCheckinCount);
        checkinCard.setClickable(false);
        stats.add(checkinCard);
        
        // 4. 异常报警
        long alertCount = reviewRecordRepository.countByReviewStatus("PENDING");
        
        // 计算昨天的异常报警数量
        long yesterdayAlertCount = reviewRecordRepository.findAll().stream()
                .filter(r -> "PENDING".equals(r.getReviewStatus()) && 
                        r.getSubmitTime() != null && 
                        r.getSubmitTime().isBefore(todayStart))
                .count();
        
        DashboardDTO.StatCard alertCard = new DashboardDTO.StatCard();
        alertCard.setTitle("异常报警");
        alertCard.setValue(String.valueOf(alertCount));
        long alertDiff = alertCount - yesterdayAlertCount;
        alertCard.setTrend(alertDiff > 0 ? "+" + alertDiff : String.valueOf(alertDiff));
        alertCard.setTrendUp(alertDiff >= 0);
        alertCard.setClickable(false);
        stats.add(alertCard);
        
        return stats;
    }
    
    /**
     * 获取待审核记录列表
     */
    private List<DashboardDTO.PendingReview> getPendingReviews(int limit) {
        Pageable pageable = PageRequest.of(0, limit);
        List<CheckinRecord> pendingRecords = checkinRecordRepository.findAll().stream()
                .filter(r -> "PENDING".equals(r.getStatus()))
                .sorted((a, b) -> {
                    if (a.getSubmitTime() == null) return 1;
                    if (b.getSubmitTime() == null) return -1;
                    return b.getSubmitTime().compareTo(a.getSubmitTime());
                })
                .limit(limit)
                .collect(Collectors.toList());
        
        // 获取所有场景配置
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        // 获取所有用户信息
        Map<Long, User> userMap = userRepository.findAll().stream()
                .collect(Collectors.toMap(User::getId, user -> user));
        
        return pendingRecords.stream().map(record -> {
            DashboardDTO.PendingReview review = new DashboardDTO.PendingReview();
            review.setId(record.getId());
            review.setCheckinId(record.getId());
            review.setImageUrl(record.getImageUrl());
            
            // 获取用户信息
            User user = userMap.get(record.getUserId());
            if (user != null) {
                review.setName(user.getNickname() != null ? user.getNickname() : user.getUsername());
            } else {
                review.setName("未知用户");
            }
            
            // 获取场景信息
            SceneConfig config = sceneConfigMap.get(record.getSceneType());
            if (config != null) {
                review.setScene(config.getTitle());
            } else {
                review.setScene(getDefaultSceneName(record.getSceneType()));
            }
            review.setSceneType(record.getSceneType());
            
            // 格式化时间（相对时间）
            if (record.getSubmitTime() != null) {
                review.setTime(formatRelativeTime(record.getSubmitTime()));
            } else {
                review.setTime("未知时间");
            }
            
            return review;
        }).collect(Collectors.toList());
    }
    
    /**
     * 获取异常报警列表
     */
    private List<DashboardDTO.AlertItem> getAlerts(int limit) {
        Pageable pageable = PageRequest.of(0, limit);
        List<ReviewRecord> alerts = reviewRecordRepository.findByReviewStatusOrderBySubmitTimeDescLimit("PENDING", pageable);
        
        return alerts.stream().map(record -> {
            DashboardDTO.AlertItem alert = new DashboardDTO.AlertItem();
            alert.setId(record.getId());
            alert.setTitle(record.getReason() != null ? record.getReason() : "异常记录");
            alert.setDesc(record.getAiReason() != null ? record.getAiReason() : "系统检测到异常");
            alert.setReasonType(record.getReasonType() != null ? record.getReasonType() : "warning");
            alert.setConfidence(record.getConfidence());
            
            // 格式化时间（相对时间）
            if (record.getSubmitTime() != null) {
                alert.setTime(formatRelativeTime(record.getSubmitTime()));
            } else {
                alert.setTime("未知时间");
            }
            
            return alert;
        }).collect(Collectors.toList());
    }
    
    /**
     * 获取场景参与占比数据（用于饼图）
     * 
     * @param timeRange 时间范围：today-今日，week-本周，month-本月
     * @return 场景参与占比数据
     */
    public List<DashboardDTO.SceneParticipationData> getSceneParticipation(String timeRange) {
        LocalDateTime startTime;
        LocalDateTime endTime = LocalDateTime.now();
        
        switch (timeRange) {
            case "week":
                startTime = LocalDate.now().minusWeeks(1).atStartOfDay();
                break;
            case "month":
                startTime = LocalDate.now().minusMonths(1).atStartOfDay();
                break;
            case "today":
            default:
                startTime = LocalDate.now().atStartOfDay();
                break;
        }
        
        // 获取指定时间范围内的打卡记录
        List<CheckinRecord> records = checkinRecordRepository.findAll().stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(startTime) && 
                        r.getSubmitTime().isBefore(endTime) &&
                        "APPROVED".equals(r.getStatus()))
                .collect(Collectors.toList());
        
        // 按场景类型统计
        Map<String, Long> sceneCountMap = records.stream()
                .collect(Collectors.groupingBy(CheckinRecord::getSceneType, Collectors.counting()));
        
        // 获取所有场景配置
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        // 计算总数
        long totalCount = sceneCountMap.values().stream().mapToLong(Long::longValue).sum();
        
        // 构建结果
        List<DashboardDTO.SceneParticipationData> result = new ArrayList<>();
        for (Map.Entry<String, Long> entry : sceneCountMap.entrySet()) {
            DashboardDTO.SceneParticipationData data = new DashboardDTO.SceneParticipationData();
            data.setSceneType(entry.getKey());
            
            SceneConfig config = sceneConfigMap.get(entry.getKey());
            if (config != null) {
                data.setSceneName(config.getTitle());
            } else {
                data.setSceneName(getDefaultSceneName(entry.getKey()));
            }
            
            data.setCount(entry.getValue().intValue());
            data.setPercentage(totalCount > 0 ? (entry.getValue().doubleValue() / totalCount) * 100 : 0.0);
            
            result.add(data);
        }
        
        // 按占比降序排序
        result.sort((a, b) -> Double.compare(b.getPercentage(), a.getPercentage()));
        
        return result;
    }
    
    /**
     * 获取近七日活跃度数据（用于折线图）
     * 
     * @return 近七日活跃度数据
     */
    public List<DashboardDTO.ActivityData> getActivityData() {
        List<DashboardDTO.ActivityData> result = new ArrayList<>();
        
        LocalDate today = LocalDate.now();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("MM-dd");
        
        // 获取近7天的数据
        for (int i = 6; i >= 0; i--) {
            LocalDate date = today.minusDays(i);
            LocalDateTime startTime = date.atStartOfDay();
            LocalDateTime endTime = date.atTime(LocalTime.MAX);
            
            // 获取当天的打卡记录（只统计成功打卡的记录）
            List<CheckinRecord> dayRecords = checkinRecordRepository.findAll().stream()
                    .filter(r -> r.getSubmitTime() != null && 
                            r.getSubmitTime().isAfter(startTime) && 
                            r.getSubmitTime().isBefore(endTime) &&
                            "APPROVED".equals(r.getStatus()))
                    .collect(Collectors.toList());
            
            // 统计活跃用户数（去重）
            long activeUsers = dayRecords.stream()
                    .map(CheckinRecord::getUserId)
                    .distinct()
                    .count();
            
            DashboardDTO.ActivityData data = new DashboardDTO.ActivityData();
            data.setDate(date.format(formatter));
            data.setActiveUsers((int) activeUsers);
            data.setCheckinCount(dayRecords.size());
            
            result.add(data);
        }
        
        return result;
    }
    
    /**
     * 格式化数字（添加千分位）
     */
    private String formatNumber(long number) {
        return String.format("%,d", number);
    }
    
    /**
     * 计算趋势百分比
     */
    private String calculateTrend(double current, double previous, boolean isPercentage) {
        if (previous == 0) {
            return current > 0 ? "+100%" : "0%";
        }
        double change = ((current - previous) / previous) * 100;
        String sign = change >= 0 ? "+" : "";
        if (isPercentage) {
            return String.format("%s%.1f%%", sign, change);
        } else {
            return String.format("%s%.1f%%", sign, change);
        }
    }
    
    /**
     * 格式化相对时间
     */
    private String formatRelativeTime(LocalDateTime time) {
        LocalDateTime now = LocalDateTime.now();
        long minutes = ChronoUnit.MINUTES.between(time, now);
        
        if (minutes < 1) {
            return "刚刚";
        } else if (minutes < 60) {
            return minutes + "分钟前";
        } else {
            long hours = ChronoUnit.HOURS.between(time, now);
            if (hours < 24) {
                return hours + "小时前";
            } else {
                long days = ChronoUnit.DAYS.between(time, now);
                return days + "天前";
            }
        }
    }
    
    /**
     * 计算场景参与占比分析
     * 
     * @param participationData 场景参与占比数据
     * @param timeRange 时间范围
     * @return 分析结果
     */
    public DashboardDTO.SceneParticipationAnalysis calculateSceneParticipationAnalysis(
            List<DashboardDTO.SceneParticipationData> participationData, String timeRange) {
        
        DashboardDTO.SceneParticipationAnalysis analysis = new DashboardDTO.SceneParticipationAnalysis();
        analysis.setSource("backend");
        
        if (participationData == null || participationData.isEmpty()) {
            analysis.setAnalysis("暂无数据，无法进行分析。");
            analysis.setInsights(List.of("数据为空"));
            analysis.setRecommendations(List.of("请等待数据积累"));
            return analysis;
        }
        
        // 找出占比最高和最低的场景
        DashboardDTO.SceneParticipationData maxScene = participationData.get(0);
        DashboardDTO.SceneParticipationData minScene = participationData.get(participationData.size() - 1);
        
        // 计算平均占比
        double avgPercentage = participationData.stream()
                .mapToDouble(DashboardDTO.SceneParticipationData::getPercentage)
                .average()
                .orElse(0.0);
        
        // 构建分析文本
        StringBuilder analysisText = new StringBuilder();
        String timeRangeText = "今日";
        if ("week".equals(timeRange)) {
            timeRangeText = "本周";
        } else if ("month".equals(timeRange)) {
            timeRangeText = "本月";
        }
        
        analysisText.append(String.format("根据%s数据统计，各场景参与度分布如下：\n\n", timeRangeText));
        analysisText.append(String.format("• 参与度最高的场景：%s（%.1f%%），共%d次参与\n", 
                maxScene.getSceneName(), maxScene.getPercentage(), maxScene.getCount()));
        analysisText.append(String.format("• 参与度最低的场景：%s（%.1f%%），共%d次参与\n", 
                minScene.getSceneName(), minScene.getPercentage(), minScene.getCount()));
        analysisText.append(String.format("• 平均参与度：%.1f%%\n\n", avgPercentage));
        
        // 分析差异
        double diff = maxScene.getPercentage() - minScene.getPercentage();
        if (diff > 30) {
            analysisText.append("各场景参与度差异较大，建议加大对参与度较低场景的宣传力度。");
        } else if (diff > 15) {
            analysisText.append("各场景参与度存在一定差异，建议平衡各场景的推广力度。");
        } else {
            analysisText.append("各场景参与度较为均衡，整体分布良好。");
        }
        
        analysis.setAnalysis(analysisText.toString());
        
        // 关键洞察
        List<String> insights = new ArrayList<>();
        insights.add(String.format("%s参与度最高（%.1f%%）", maxScene.getSceneName(), maxScene.getPercentage()));
        if (diff > 20) {
            insights.add(String.format("%s与%s参与度差异较大（%.1f%%）", 
                    maxScene.getSceneName(), minScene.getSceneName(), diff));
        }
        if (avgPercentage > 20) {
            insights.add("整体参与度较高，用户活跃度良好");
        }
        analysis.setInsights(insights);
        
        // 改进建议
        List<String> recommendations = new ArrayList<>();
        if (minScene.getPercentage() < 10) {
            recommendations.add(String.format("建议加大对%s场景的宣传和激励力度", minScene.getSceneName()));
        }
        if (diff > 25) {
            recommendations.add("考虑设置场景参与奖励机制，鼓励用户尝试不同场景");
        }
        recommendations.add("定期分析各场景参与数据，及时调整推广策略");
        analysis.setRecommendations(recommendations);
        
        return analysis;
    }
    
    /**
     * 计算活跃度趋势分析（后端计算，AI断联时的备用方案）
     * 
     * @param activityData 活跃度数据
     * @return 分析结果
     */
    public DashboardDTO.ActivityTrendAnalysis calculateActivityTrendAnalysis(
            List<DashboardDTO.ActivityData> activityData) {
        
        DashboardDTO.ActivityTrendAnalysis analysis = new DashboardDTO.ActivityTrendAnalysis();
        analysis.setSource("backend");
        
        if (activityData == null || activityData.size() < 2) {
            analysis.setAnalysis("数据不足，无法进行趋势分析。");
            analysis.setTrend("平稳");
            analysis.setInsights(List.of("数据不足"));
            return analysis;
        }
        
        // 找出峰值日期
        DashboardDTO.ActivityData peakDay = activityData.stream()
                .max((a, b) -> Integer.compare(a.getActiveUsers(), b.getActiveUsers()))
                .orElse(activityData.get(0));
        analysis.setPeakDay(peakDay.getDate());
        
        // 计算趋势
        int firstDayUsers = activityData.get(0).getActiveUsers();
        int lastDayUsers = activityData.get(activityData.size() - 1).getActiveUsers();
        double changeRate = firstDayUsers > 0 ? 
                ((lastDayUsers - firstDayUsers) * 100.0 / firstDayUsers) : 0;
        
        String trend;
        if (changeRate > 10) {
            trend = "上升";
        } else if (changeRate < -10) {
            trend = "下降";
        } else {
            trend = "平稳";
        }
        analysis.setTrend(trend);
        
        // 构建分析文本
        StringBuilder analysisText = new StringBuilder();
        analysisText.append("近七日系统活跃度分析：\n\n");
        analysisText.append(String.format("• 首日活跃用户：%d人\n", firstDayUsers));
        analysisText.append(String.format("• 最后一日活跃用户：%d人\n", lastDayUsers));
        analysisText.append(String.format("• 变化幅度：%.1f%%\n", changeRate));
        analysisText.append(String.format("• 峰值日期：%s（%d人）\n\n", peakDay.getDate(), peakDay.getActiveUsers()));
        
        if ("上升".equals(trend)) {
            analysisText.append("整体趋势呈上升态势，系统活跃度持续提升，用户参与积极性较高。");
        } else if ("下降".equals(trend)) {
            analysisText.append("整体趋势呈下降态势，建议加强用户激励和推广活动，提升系统活跃度。");
        } else {
            analysisText.append("整体趋势保持平稳，系统活跃度稳定，建议继续保持并寻求突破。");
        }
        
        analysis.setAnalysis(analysisText.toString());
        
        // 关键洞察
        List<String> insights = new ArrayList<>();
        insights.add(String.format("整体趋势：%s（变化%.1f%%）", trend, changeRate));
        insights.add(String.format("峰值出现在%s，活跃用户%d人", peakDay.getDate(), peakDay.getActiveUsers()));
        
        // 计算平均活跃度
        double avgActiveUsers = activityData.stream()
                .mapToInt(DashboardDTO.ActivityData::getActiveUsers)
                .average()
                .orElse(0.0);
        insights.add(String.format("平均日活跃用户：%.0f人", avgActiveUsers));
        
        analysis.setInsights(insights);
        
        return analysis;
    }
    
    /**
     * 获取个人统计数据
     * 
     * @param userId 用户ID
     * @param timeRange 时间范围：week-近7天，month-近30天
     * @return 个人统计数据
     */
    public DashboardDTO.PersonalStatsData getPersonalStats(Long userId, String timeRange) {
        DashboardDTO.PersonalStatsData stats = new DashboardDTO.PersonalStatsData();
        
        // 确定时间范围
        LocalDate today = LocalDate.now();
        LocalDateTime startTime;
        int days;
        if ("month".equals(timeRange)) {
            startTime = today.minusDays(30).atStartOfDay();
            days = 30;
        } else {
            startTime = today.minusDays(7).atStartOfDay();
            days = 7;
        }
        LocalDateTime endTime = today.plusDays(1).atStartOfDay();
        
        // 获取用户的打卡记录
        List<CheckinRecord> userRecords = checkinRecordRepository.findByUserId(userId).stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(startTime) && 
                        r.getSubmitTime().isBefore(endTime) &&
                        "APPROVED".equals(r.getStatus()))
                .sorted((a, b) -> a.getSubmitTime().compareTo(b.getSubmitTime()))
                .collect(Collectors.toList());
        
        // 1. 获取打卡趋势数据（按日期统计）
        List<DashboardDTO.PersonalCheckinTrend> checkinTrend = new ArrayList<>();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("MM-dd");
        
        for (int i = days - 1; i >= 0; i--) {
            LocalDate date = today.minusDays(i);
            LocalDateTime dayStart = date.atStartOfDay();
            LocalDateTime dayEnd = date.plusDays(1).atStartOfDay();
            
            long dayCount = userRecords.stream()
                    .filter(r -> r.getSubmitTime() != null && 
                            r.getSubmitTime().isAfter(dayStart) && 
                            r.getSubmitTime().isBefore(dayEnd))
                    .count();
            
            DashboardDTO.PersonalCheckinTrend trend = new DashboardDTO.PersonalCheckinTrend();
            trend.setDate(date.format(formatter));
            trend.setCount((int) dayCount);
            checkinTrend.add(trend);
        }
        stats.setCheckinTrend(checkinTrend);
        
        // 2. 获取场景分布数据
        Map<String, Long> sceneCountMap = userRecords.stream()
                .collect(Collectors.groupingBy(CheckinRecord::getSceneType, Collectors.counting()));
        
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        long totalCount = sceneCountMap.values().stream().mapToLong(Long::longValue).sum();
        
        List<DashboardDTO.PersonalSceneDistribution> sceneDistribution = new ArrayList<>();
        for (Map.Entry<String, Long> entry : sceneCountMap.entrySet()) {
            DashboardDTO.PersonalSceneDistribution dist = new DashboardDTO.PersonalSceneDistribution();
            dist.setSceneType(entry.getKey());
            
            SceneConfig config = sceneConfigMap.get(entry.getKey());
            if (config != null) {
                dist.setSceneName(config.getTitle());
                dist.setIcon(config.getIcon());
            } else {
                dist.setSceneName(getDefaultSceneName(entry.getKey()));
                dist.setIcon(getDefaultSceneIcon(entry.getKey()));
            }
            
            dist.setCount(entry.getValue().intValue());
            dist.setPercentage(totalCount > 0 ? (entry.getValue().doubleValue() / totalCount) * 100 : 0.0);
            sceneDistribution.add(dist);
        }
        
        // 按占比降序排序
        sceneDistribution.sort((a, b) -> Double.compare(b.getPercentage(), a.getPercentage()));
        stats.setSceneDistribution(sceneDistribution);
        
        // 3. 获取减碳量统计
        DashboardDTO.PersonalCarbonStats carbonStats = new DashboardDTO.PersonalCarbonStats();
        
        BigDecimal totalCarbon = BigDecimal.ZERO;
        BigDecimal monthlyCarbon = BigDecimal.ZERO;
        BigDecimal weeklyCarbon = BigDecimal.ZERO;
        
        LocalDate monthStart = today.withDayOfMonth(1);
        LocalDate weekStart = today.minusDays(7);
        
        for (CheckinRecord record : userRecords) {
            SceneConfig config = sceneConfigMap.get(record.getSceneType());
            if (config != null && config.getCarbonReduction() != null) {
                BigDecimal carbon = config.getCarbonReduction();
                totalCarbon = totalCarbon.add(carbon);
                
                if (record.getSubmitTime() != null) {
                    LocalDate recordDate = record.getSubmitTime().toLocalDate();
                    if (!recordDate.isBefore(monthStart)) {
                        monthlyCarbon = monthlyCarbon.add(carbon);
                    }
                    if (!recordDate.isBefore(weekStart)) {
                        weeklyCarbon = weeklyCarbon.add(carbon);
                    }
                }
            }
        }
        
        carbonStats.setTotalCarbonReduction(totalCarbon.doubleValue());
        carbonStats.setMonthlyCarbonReduction(monthlyCarbon.doubleValue());
        carbonStats.setWeeklyCarbonReduction(weeklyCarbon.doubleValue());
        stats.setCarbonStats(carbonStats);
        
        // 4. 获取积分获取趋势
        DashboardDTO.PersonalPointsTrend pointsTrend = new DashboardDTO.PersonalPointsTrend();
        
        // 每日积分获取（近7天）
        List<DashboardDTO.PersonalCheckinTrend> dailyPoints = new ArrayList<>();
        for (int i = 6; i >= 0; i--) {
            LocalDate date = today.minusDays(i);
            LocalDateTime dayStart = date.atStartOfDay();
            LocalDateTime dayEnd = date.plusDays(1).atStartOfDay();
            
            int dayPoints = userRecords.stream()
                    .filter(r -> r.getSubmitTime() != null && 
                            r.getSubmitTime().isAfter(dayStart) && 
                            r.getSubmitTime().isBefore(dayEnd))
                    .mapToInt(r -> r.getRewardPoints() != null ? r.getRewardPoints() : 0)
                    .sum();
            
            DashboardDTO.PersonalCheckinTrend trend = new DashboardDTO.PersonalCheckinTrend();
            trend.setDate(date.format(formatter));
            trend.setCount(dayPoints);
            dailyPoints.add(trend);
        }
        pointsTrend.setDailyPoints(dailyPoints);
        
        // 总积分、本月积分、本周积分
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        pointsTrend.setTotalPoints(user.getPoints() != null ? user.getPoints() : 0);
        
        int monthlyPoints = userRecords.stream()
                .filter(r -> r.getSubmitTime() != null && 
                        !r.getSubmitTime().toLocalDate().isBefore(monthStart))
                .mapToInt(r -> r.getRewardPoints() != null ? r.getRewardPoints() : 0)
                .sum();
        pointsTrend.setMonthlyPoints(monthlyPoints);
        
        int weeklyPoints = userRecords.stream()
                .filter(r -> r.getSubmitTime() != null && 
                        !r.getSubmitTime().toLocalDate().isBefore(weekStart))
                .mapToInt(r -> r.getRewardPoints() != null ? r.getRewardPoints() : 0)
                .sum();
        pointsTrend.setWeeklyPoints(weeklyPoints);
        
        stats.setPointsTrend(pointsTrend);
        
        return stats;
    }
    
    /**
     * 计算个人数据详细分析（用于AI分析）
     * 
     * @param userId 用户ID
     * @param timeRange 时间范围：week-近7天，month-近30天
     * @return 详细分析结果
     */
    public DashboardDTO.PersonalDataCalculation calculatePersonalDataAnalysis(Long userId, String timeRange) {
        DashboardDTO.PersonalDataCalculation calculation = new DashboardDTO.PersonalDataCalculation();
        
        // 确定时间范围
        LocalDate today = LocalDate.now();
        LocalDateTime startTime;
        int days;
        if ("month".equals(timeRange)) {
            startTime = today.minusDays(30).atStartOfDay();
            days = 30;
        } else {
            startTime = today.minusDays(7).atStartOfDay();
            days = 7;
        }
        LocalDateTime endTime = today.plusDays(1).atStartOfDay();
        
        // 获取用户的打卡记录
        List<CheckinRecord> userRecords = checkinRecordRepository.findByUserId(userId).stream()
                .filter(r -> r.getSubmitTime() != null && 
                        r.getSubmitTime().isAfter(startTime) && 
                        r.getSubmitTime().isBefore(endTime) &&
                        "APPROVED".equals(r.getStatus()))
                .sorted((a, b) -> a.getSubmitTime().compareTo(b.getSubmitTime()))
                .collect(Collectors.toList());
        
        // 获取场景配置
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        // 1. 打卡趋势分析
        DashboardDTO.CheckinTrendAnalysis checkinTrendAnalysis = calculateCheckinTrendAnalysis(userRecords, days);
        calculation.setCheckinTrendAnalysis(checkinTrendAnalysis);
        
        // 2. 场景分布分析
        DashboardDTO.SceneDistributionAnalysis sceneDistributionAnalysis = calculateSceneDistributionAnalysis(userRecords, sceneConfigMap);
        calculation.setSceneDistributionAnalysis(sceneDistributionAnalysis);
        
        // 3. 减碳量分析
        DashboardDTO.CarbonReductionAnalysis carbonReductionAnalysis = calculateCarbonReductionAnalysis(userRecords, sceneConfigMap, today);
        calculation.setCarbonReductionAnalysis(carbonReductionAnalysis);
        
        // 4. 积分分析
        DashboardDTO.PointsAnalysis pointsAnalysis = calculatePointsAnalysis(userRecords, userId, today);
        calculation.setPointsAnalysis(pointsAnalysis);
        
        // 5. 综合评估
        DashboardDTO.OverallAssessment overallAssessment = calculateOverallAssessment(
                checkinTrendAnalysis, sceneDistributionAnalysis, carbonReductionAnalysis, pointsAnalysis);
        calculation.setOverallAssessment(overallAssessment);
        
        return calculation;
    }
    
    /**
     * 计算打卡趋势分析
     */
    private DashboardDTO.CheckinTrendAnalysis calculateCheckinTrendAnalysis(List<CheckinRecord> records, int days) {
        DashboardDTO.CheckinTrendAnalysis analysis = new DashboardDTO.CheckinTrendAnalysis();
        
        // 按日期统计打卡次数
        Map<LocalDate, Long> dailyCounts = records.stream()
                .filter(r -> r.getSubmitTime() != null)
                .collect(Collectors.groupingBy(
                        r -> r.getSubmitTime().toLocalDate(),
                        Collectors.counting()
                ));
        
        // 计算平均值
        double avgDaily = dailyCounts.values().stream()
                .mapToLong(Long::longValue)
                .average()
                .orElse(0.0);
        analysis.setAverageDailyCheckins(avgDaily);
        
        // 计算最大值和最小值
        if (!dailyCounts.isEmpty()) {
            long maxCount = dailyCounts.values().stream().mapToLong(Long::longValue).max().orElse(0);
            long minCount = dailyCounts.values().stream().mapToLong(Long::longValue).min().orElse(0);
            analysis.setMaxDailyCheckins((int) maxCount);
            analysis.setMinDailyCheckins((int) minCount);
        } else {
            analysis.setMaxDailyCheckins(0);
            analysis.setMinDailyCheckins(0);
        }
        
        // 计算趋势（比较前半段和后半段）
        if (dailyCounts.size() >= 4) {
            List<LocalDate> sortedDates = dailyCounts.keySet().stream()
                    .sorted()
                    .collect(Collectors.toList());
            
            int mid = sortedDates.size() / 2;
            double firstHalfAvg = sortedDates.subList(0, mid).stream()
                    .mapToLong(dailyCounts::get)
                    .average()
                    .orElse(0.0);
            double secondHalfAvg = sortedDates.subList(mid, sortedDates.size()).stream()
                    .mapToLong(dailyCounts::get)
                    .average()
                    .orElse(0.0);
            
            double changeRate = firstHalfAvg > 0 ? 
                    ((secondHalfAvg - firstHalfAvg) / firstHalfAvg) * 100 : 0;
            analysis.setTrendRate(changeRate);
            
            if (changeRate > 10) {
                analysis.setTrend("上升");
            } else if (changeRate < -10) {
                analysis.setTrend("下降");
            } else {
                analysis.setTrend("平稳");
            }
        } else {
            analysis.setTrend("数据不足");
            analysis.setTrendRate(0.0);
        }
        
        // 计算连续打卡天数
        LocalDate today = LocalDate.now();
        int consecutiveDays = 0;
        for (int i = 0; i < days; i++) {
            LocalDate date = today.minusDays(i);
            if (dailyCounts.containsKey(date)) {
                consecutiveDays++;
            } else {
                break;
            }
        }
        analysis.setConsecutiveDays(consecutiveDays);
        
        // 活跃天数
        analysis.setActiveDays(dailyCounts.size());
        
        // 一致性评价
        double consistencyScore = (double) consecutiveDays / days * 100;
        if (consistencyScore >= 80) {
            analysis.setConsistency("优秀");
        } else if (consistencyScore >= 60) {
            analysis.setConsistency("良好");
        } else if (consistencyScore >= 40) {
            analysis.setConsistency("一般");
        } else {
            analysis.setConsistency("需改进");
        }
        
        return analysis;
    }
    
    /**
     * 计算场景分布分析
     */
    private DashboardDTO.SceneDistributionAnalysis calculateSceneDistributionAnalysis(
            List<CheckinRecord> records, Map<String, SceneConfig> sceneConfigMap) {
        DashboardDTO.SceneDistributionAnalysis analysis = new DashboardDTO.SceneDistributionAnalysis();
        
        // 按场景统计
        Map<String, Long> sceneCounts = records.stream()
                .collect(Collectors.groupingBy(CheckinRecord::getSceneType, Collectors.counting()));
        
        long totalCount = sceneCounts.values().stream().mapToLong(Long::longValue).sum();
        
        if (sceneCounts.isEmpty()) {
            analysis.setFavoriteScene("无");
            analysis.setFavoriteScenePercentage(0.0);
            analysis.setLeastFavoriteScene("无");
            analysis.setLeastFavoriteScenePercentage(0.0);
            analysis.setDiversityScore(0.0);
            analysis.setDiversityLevel("低");
            analysis.setMissingScenes(List.of("walk", "ride", "plate", "transit"));
            return analysis;
        }
        
        // 找出最偏好和最少参与的场景
        String favoriteScene = sceneCounts.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse("无");
        String leastFavoriteScene = sceneCounts.entrySet().stream()
                .min(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse("无");
        
        SceneConfig favoriteConfig = sceneConfigMap.get(favoriteScene);
        SceneConfig leastFavoriteConfig = sceneConfigMap.get(leastFavoriteScene);
        
        analysis.setFavoriteScene(favoriteConfig != null ? favoriteConfig.getTitle() : favoriteScene);
        analysis.setFavoriteScenePercentage(totalCount > 0 ? 
                (sceneCounts.get(favoriteScene).doubleValue() / totalCount) * 100 : 0.0);
        analysis.setLeastFavoriteScene(leastFavoriteConfig != null ? 
                leastFavoriteConfig.getTitle() : leastFavoriteScene);
        analysis.setLeastFavoriteScenePercentage(totalCount > 0 ? 
                (sceneCounts.get(leastFavoriteScene).doubleValue() / totalCount) * 100 : 0.0);
        
        // 计算多样性得分（参与的场景数量 / 总场景数量 * 100）
        double diversityScore = (sceneCounts.size() / 4.0) * 100;
        analysis.setDiversityScore(diversityScore);
        
        if (diversityScore >= 75) {
            analysis.setDiversityLevel("高");
        } else if (diversityScore >= 50) {
            analysis.setDiversityLevel("中");
        } else {
            analysis.setDiversityLevel("低");
        }
        
        // 找出未参与的场景
        List<String> allScenes = List.of("walk", "ride", "plate", "transit");
        List<String> missingScenes = allScenes.stream()
                .filter(scene -> !sceneCounts.containsKey(scene))
                .map(scene -> {
                    SceneConfig config = sceneConfigMap.get(scene);
                    return config != null ? config.getTitle() : scene;
                })
                .collect(Collectors.toList());
        analysis.setMissingScenes(missingScenes);
        
        return analysis;
    }
    
    /**
     * 计算减碳量分析
     */
    private DashboardDTO.CarbonReductionAnalysis calculateCarbonReductionAnalysis(
            List<CheckinRecord> records, Map<String, SceneConfig> sceneConfigMap, LocalDate today) {
        DashboardDTO.CarbonReductionAnalysis analysis = new DashboardDTO.CarbonReductionAnalysis();
        
        LocalDate monthStart = today.withDayOfMonth(1);
        LocalDate weekStart = today.minusDays(7);
        LocalDate lastMonthStart = monthStart.minusMonths(1);
        LocalDate lastWeekStart = weekStart.minusDays(7);
        
        BigDecimal totalCarbon = BigDecimal.ZERO;
        BigDecimal monthlyCarbon = BigDecimal.ZERO;
        BigDecimal weeklyCarbon = BigDecimal.ZERO;
        BigDecimal lastMonthCarbon = BigDecimal.ZERO;
        BigDecimal lastWeekCarbon = BigDecimal.ZERO;
        
        for (CheckinRecord record : records) {
            SceneConfig config = sceneConfigMap.get(record.getSceneType());
            if (config != null && config.getCarbonReduction() != null) {
                BigDecimal carbon = config.getCarbonReduction();
                totalCarbon = totalCarbon.add(carbon);
                
                if (record.getSubmitTime() != null) {
                    LocalDate recordDate = record.getSubmitTime().toLocalDate();
                    if (!recordDate.isBefore(monthStart)) {
                        monthlyCarbon = monthlyCarbon.add(carbon);
                    }
                    if (!recordDate.isBefore(weekStart)) {
                        weeklyCarbon = weeklyCarbon.add(carbon);
                    }
                    if (!recordDate.isBefore(lastMonthStart) && recordDate.isBefore(monthStart)) {
                        lastMonthCarbon = lastMonthCarbon.add(carbon);
                    }
                    if (!recordDate.isBefore(lastWeekStart) && recordDate.isBefore(weekStart)) {
                        lastWeekCarbon = lastWeekCarbon.add(carbon);
                    }
                }
            }
        }
        
        analysis.setTotalCarbonReduction(totalCarbon.doubleValue());
        analysis.setMonthlyCarbonReduction(monthlyCarbon.doubleValue());
        analysis.setWeeklyCarbonReduction(weeklyCarbon.doubleValue());
        
        // 计算平均每日减碳量（基于活跃天数）
        long activeDays = records.stream()
                .filter(r -> r.getSubmitTime() != null)
                .map(r -> r.getSubmitTime().toLocalDate())
                .distinct()
                .count();
        analysis.setAverageDailyCarbonReduction(activeDays > 0 ? 
                totalCarbon.divide(BigDecimal.valueOf(activeDays), 4, java.math.RoundingMode.HALF_UP).doubleValue() : 0.0);
        
        // 计算增长率
        double monthlyGrowthRate = lastMonthCarbon.compareTo(BigDecimal.ZERO) > 0 ?
                ((monthlyCarbon.subtract(lastMonthCarbon)).divide(lastMonthCarbon, 4, java.math.RoundingMode.HALF_UP).doubleValue()) * 100 : 0.0;
        double weeklyGrowthRate = lastWeekCarbon.compareTo(BigDecimal.ZERO) > 0 ?
                ((weeklyCarbon.subtract(lastWeekCarbon)).divide(lastWeekCarbon, 4, java.math.RoundingMode.HALF_UP).doubleValue()) * 100 : 0.0;
        analysis.setMonthlyGrowthRate(monthlyGrowthRate);
        analysis.setWeeklyGrowthRate(weeklyGrowthRate);
        
        // 贡献等级（基于累计减碳量）
        double total = totalCarbon.doubleValue();
        if (total >= 50) {
            analysis.setContributionLevel("卓越");
        } else if (total >= 20) {
            analysis.setContributionLevel("优秀");
        } else if (total >= 10) {
            analysis.setContributionLevel("良好");
        } else {
            analysis.setContributionLevel("一般");
        }
        
        // 等价描述（1kg CO2 ≈ 种植0.05棵树）
        int trees = (int) (total * 0.05);
        analysis.setEquivalentDescription(String.format("相当于种植%d棵树", trees));
        
        return analysis;
    }
    
    /**
     * 计算积分分析
     */
    private DashboardDTO.PointsAnalysis calculatePointsAnalysis(
            List<CheckinRecord> records, Long userId, LocalDate today) {
        DashboardDTO.PointsAnalysis analysis = new DashboardDTO.PointsAnalysis();
        
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        LocalDate monthStart = today.withDayOfMonth(1);
        LocalDate weekStart = today.minusDays(7);
        LocalDate lastMonthStart = monthStart.minusMonths(1);
        LocalDate lastWeekStart = weekStart.minusDays(7);
        
        int totalPoints = user.getPoints() != null ? user.getPoints() : 0;
        int monthlyPoints = 0;
        int weeklyPoints = 0;
        int lastMonthPoints = 0;
        int lastWeekPoints = 0;
        int maxDailyPoints = 0;
        
        // 按日期统计积分
        Map<LocalDate, Integer> dailyPoints = new HashMap<>();
        
        for (CheckinRecord record : records) {
            int points = record.getRewardPoints() != null ? record.getRewardPoints() : 0;
            
            if (record.getSubmitTime() != null) {
                LocalDate recordDate = record.getSubmitTime().toLocalDate();
                dailyPoints.merge(recordDate, points, Integer::sum);
                
                if (!recordDate.isBefore(monthStart)) {
                    monthlyPoints += points;
                }
                if (!recordDate.isBefore(weekStart)) {
                    weeklyPoints += points;
                }
                if (!recordDate.isBefore(lastMonthStart) && recordDate.isBefore(monthStart)) {
                    lastMonthPoints += points;
                }
                if (!recordDate.isBefore(lastWeekStart) && recordDate.isBefore(weekStart)) {
                    lastWeekPoints += points;
                }
            }
        }
        
        // 找出单日最高积分
        if (!dailyPoints.isEmpty()) {
            maxDailyPoints = dailyPoints.values().stream().mapToInt(Integer::intValue).max().orElse(0);
        }
        
        // 计算平均每日积分
        long activeDays = dailyPoints.size();
        double avgDailyPoints = activeDays > 0 ? (double) weeklyPoints / activeDays : 0.0;
        
        analysis.setTotalPoints(totalPoints);
        analysis.setMonthlyPoints(monthlyPoints);
        analysis.setWeeklyPoints(weeklyPoints);
        analysis.setAverageDailyPoints(avgDailyPoints);
        analysis.setMaxDailyPoints(maxDailyPoints);
        
        // 计算增长率
        double monthlyGrowthRate = lastMonthPoints > 0 ? 
                ((double)(monthlyPoints - lastMonthPoints) / lastMonthPoints) * 100 : 0.0;
        double weeklyGrowthRate = lastWeekPoints > 0 ? 
                ((double)(weeklyPoints - lastWeekPoints) / lastWeekPoints) * 100 : 0.0;
        analysis.setMonthlyGrowthRate(monthlyGrowthRate);
        analysis.setWeeklyGrowthRate(weeklyGrowthRate);
        
        // 活跃度等级（基于平均每日积分）
        if (avgDailyPoints >= 30) {
            analysis.setActivityLevel("极高");
        } else if (avgDailyPoints >= 20) {
            analysis.setActivityLevel("高");
        } else if (avgDailyPoints >= 10) {
            analysis.setActivityLevel("中");
        } else {
            analysis.setActivityLevel("低");
        }
        
        return analysis;
    }
    
    /**
     * 计算综合评估
     */
    private DashboardDTO.OverallAssessment calculateOverallAssessment(
            DashboardDTO.CheckinTrendAnalysis checkinTrend,
            DashboardDTO.SceneDistributionAnalysis sceneDist,
            DashboardDTO.CarbonReductionAnalysis carbon,
            DashboardDTO.PointsAnalysis points) {
        DashboardDTO.OverallAssessment assessment = new DashboardDTO.OverallAssessment();
        
        // 计算综合得分（各项指标加权平均）
        double consistencyScore = checkinTrend.getConsistency().equals("优秀") ? 100 :
                checkinTrend.getConsistency().equals("良好") ? 80 :
                checkinTrend.getConsistency().equals("一般") ? 60 : 40;
        
        double diversityScore = sceneDist.getDiversityScore();
        
        double contributionScore = carbon.getContributionLevel().equals("卓越") ? 100 :
                carbon.getContributionLevel().equals("优秀") ? 80 :
                carbon.getContributionLevel().equals("良好") ? 60 : 40;
        
        double activityScore = points.getActivityLevel().equals("极高") ? 100 :
                points.getActivityLevel().equals("高") ? 80 :
                points.getActivityLevel().equals("中") ? 60 : 40;
        
        // 加权计算：一致性30%，多样性20%，贡献度30%，活跃度20%
        int overallScore = (int) (consistencyScore * 0.3 + diversityScore * 0.2 + 
                contributionScore * 0.3 + activityScore * 0.2);
        assessment.setOverallScore(overallScore);
        
        // 综合等级
        if (overallScore >= 85) {
            assessment.setOverallLevel("优秀");
        } else if (overallScore >= 70) {
            assessment.setOverallLevel("良好");
        } else if (overallScore >= 60) {
            assessment.setOverallLevel("一般");
        } else {
            assessment.setOverallLevel("需改进");
        }
        
        // 优势点
        List<String> strengths = new ArrayList<>();
        if (consistencyScore >= 80) {
            strengths.add("打卡习惯良好，保持连续性");
        }
        if (diversityScore >= 75) {
            strengths.add("场景参与多样化，全面覆盖");
        }
        if (contributionScore >= 80) {
            strengths.add("减碳贡献突出，环保意识强");
        }
        if (activityScore >= 80) {
            strengths.add("活跃度高，积极参与");
        }
        if (strengths.isEmpty()) {
            strengths.add("已开始参与低碳行动");
        }
        assessment.setStrengths(strengths);
        
        // 待改进点
        List<String> weaknesses = new ArrayList<>();
        if (consistencyScore < 60) {
            weaknesses.add("打卡频率不稳定，建议保持每日打卡习惯");
        }
        if (diversityScore < 50) {
            weaknesses.add("场景参与单一，建议尝试更多低碳场景");
        }
        if (contributionScore < 60) {
            weaknesses.add("减碳量有待提升，建议增加打卡频率");
        }
        if (activityScore < 60) {
            weaknesses.add("活跃度较低，建议提高参与积极性");
        }
        if (!sceneDist.getMissingScenes().isEmpty()) {
            weaknesses.add(String.format("尚未参与%s场景，建议尝试", String.join("、", sceneDist.getMissingScenes())));
        }
        if (weaknesses.isEmpty()) {
            weaknesses.add("继续保持当前良好状态");
        }
        assessment.setWeaknesses(weaknesses);
        
        // 总结评价
        String summary = String.format(
                "综合得分%d分，等级为%s。%s，%s。建议%s。",
                overallScore,
                assessment.getOverallLevel(),
                String.join("；", strengths),
                weaknesses.size() > 0 ? weaknesses.get(0) : "继续保持",
                weaknesses.size() > 1 ? weaknesses.get(1) : "继续保持良好状态"
        );
        assessment.setSummary(summary);
        
        return assessment;
    }
}

