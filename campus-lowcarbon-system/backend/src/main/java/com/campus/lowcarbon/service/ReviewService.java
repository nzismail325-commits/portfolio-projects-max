/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.ReviewDTO;
import com.campus.lowcarbon.entity.CheckinRecord;
import com.campus.lowcarbon.entity.ReviewRecord;
import com.campus.lowcarbon.entity.SceneConfig;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.CheckinRecordRepository;
import com.campus.lowcarbon.repository.ReviewRecordRepository;
import com.campus.lowcarbon.repository.SceneConfigRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.NotificationService;
import com.campus.lowcarbon.service.MallService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 异常审核服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class ReviewService {
    
    private final ReviewRecordRepository reviewRecordRepository;
    private final UserRepository userRepository;
    private final CheckinRecordRepository checkinRecordRepository;
    private final SceneConfigRepository sceneConfigRepository;
    private final NotificationService notificationService;
    private final MallService mallService;
    private final ObjectMapper objectMapper = new ObjectMapper();
    
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("HH:mm:ss");
    
    // 场景类型到中文名称的映射
    private static final Map<String, String> SCENE_TYPE_MAP = new HashMap<>();
    static {
        SCENE_TYPE_MAP.put("walk", "低碳健步走");
        SCENE_TYPE_MAP.put("ride", "绿色骑行");
        SCENE_TYPE_MAP.put("plate", "光盘行动");
        SCENE_TYPE_MAP.put("transit", "公共交通");
    }
    
    // 原因类型到图标的映射
    private static final Map<String, String> REASON_ICON_MAP = new HashMap<>();
    static {
        REASON_ICON_MAP.put("warning", "🟠");
        REASON_ICON_MAP.put("danger", "🔴");
        REASON_ICON_MAP.put("info", "🟣");
    }
    
    /**
     * 获取审核列表（分页）
     * 
     * @param page 页码（从1开始）
     * @param pageSize 每页大小
     * @param sceneType 场景类型筛选（可选）
     * @return 审核列表响应
     */
    @Transactional(readOnly = true)
    public ReviewDTO.ReviewListResponse getReviewList(Integer page, Integer pageSize, String sceneType) {
        // 页码从1开始，转换为从0开始
        int pageIndex = (page == null || page < 1) ? 0 : page - 1;
        int size = (pageSize == null || pageSize < 1) ? 10 : pageSize;
        
        Pageable pageable = PageRequest.of(pageIndex, size);
        
        // 查询待审核记录
        Page<ReviewRecord> reviewPage;
        if (sceneType != null && !sceneType.trim().isEmpty()) {
            reviewPage = reviewRecordRepository.findByReviewStatusAndSceneTypeOrderBySubmitTimeDesc(
                    "PENDING", sceneType.trim(), pageable);
        } else {
            reviewPage = reviewRecordRepository.findByReviewStatusOrderBySubmitTimeDesc(
                    "PENDING", pageable);
        }
        
        // 转换为DTO
        List<ReviewDTO.ReviewRecordInfo> records = reviewPage.getContent().stream()
                .map(this::convertToReviewRecordInfo)
                .collect(Collectors.toList());
        
        // 获取统计数据
        ReviewDTO.ReviewStatistics statistics = getReviewStatistics();
        
        // 构建响应
        ReviewDTO.ReviewListResponse response = new ReviewDTO.ReviewListResponse();
        response.setRecords(records);
        response.setStatistics(statistics);
        response.setTotal(reviewPage.getTotalElements());
        response.setPage(pageIndex + 1);
        response.setPageSize(size);
        
        return response;
    }
    
    /**
     * 获取审核统计数据
     * 
     * @return 统计数据
     */
    @Transactional(readOnly = true)
    public ReviewDTO.ReviewStatistics getReviewStatistics() {
        ReviewDTO.ReviewStatistics statistics = new ReviewDTO.ReviewStatistics();
        
        // 待处理异常数量
        statistics.setPendingCount(reviewRecordRepository.countByReviewStatus("PENDING"));
        
        // 今日开始和结束时间
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime todayEnd = LocalDateTime.of(LocalDate.now(), LocalTime.MAX);
        
        // 今日自动驳回数量（reviewer_id为NULL的REJECTED记录）
        long rejectedCount = reviewRecordRepository.countTodayAutoRejected(todayStart, todayEnd);
        statistics.setTodayRejectedCount(rejectedCount);
        
        // 今日人工复核通过数量（reviewer_id不为NULL的APPROVED记录）
        long manualApprovedCount = reviewRecordRepository.countTodayManualApproved(todayStart, todayEnd);
        statistics.setTodayApprovedCount(manualApprovedCount);
        
        // 今日AI自动通过数量（reviewer_id为NULL的APPROVED记录）
        long aiApprovedCount = reviewRecordRepository.countTodayAiApproved(todayStart, todayEnd);
        statistics.setTodayAiApprovedCount(aiApprovedCount);
        
        log.info("审核统计数据: pendingCount={}, todayRejectedCount={}, todayApprovedCount={}, todayAiApprovedCount={}", 
                statistics.getPendingCount(), rejectedCount, manualApprovedCount, aiApprovedCount);
        
        return statistics;
    }
    
    /**
     * 审核操作（通过或驳回）
     * 
     * @param reviewId 审核记录ID
     * @param action 操作类型：APPROVE-通过，REJECT-驳回
     * @param comment 审核意见（驳回时必填）
     * @param reviewerId 审核人ID（管理员）
     * @param extractedValue 提取的数值（步数/里程，仅walk和ride类型需要，可选）
     * @return 审核操作响应
     */
    @Transactional
    public ReviewDTO.ReviewActionResponse reviewAction(Long reviewId, String action, String comment, Long reviewerId, Double extractedValue) {
        // 查找审核记录
        ReviewRecord reviewRecord = reviewRecordRepository.findById(reviewId)
                .orElseThrow(() -> new BusinessException("审核记录不存在"));
        
        // 检查是否已处理
        if (!"PENDING".equals(reviewRecord.getReviewStatus())) {
            throw new BusinessException("该记录已处理，无法重复操作");
        }
        
        // 验证操作类型
        if (!"APPROVE".equals(action) && !"REJECT".equals(action)) {
            throw new BusinessException("无效的操作类型");
        }
        
        // 驳回时必须提供审核意见
        if ("REJECT".equals(action) && (comment == null || comment.trim().isEmpty())) {
            throw new BusinessException("驳回操作必须提供审核意见");
        }
        
        // 更新审核记录
        reviewRecord.setReviewStatus(action.equals("APPROVE") ? "APPROVED" : "REJECTED");
        reviewRecord.setReviewerId(reviewerId);
        reviewRecord.setReviewComment(comment);
        reviewRecord.setReviewTime(LocalDateTime.now());
        reviewRecordRepository.save(reviewRecord);
        
        // 更新打卡记录状态
        CheckinRecord checkinRecord = checkinRecordRepository.findById(reviewRecord.getCheckinId())
                .orElseThrow(() -> new BusinessException("打卡记录不存在"));
        
        if ("APPROVE".equals(action)) {
            // 人工复核通过：更新打卡记录为已通过，更新用户统计（前端会根据统计判断是否可解锁勋章）
            checkinRecord.setStatus("APPROVED");
            checkinRecord.setVerifyTime(LocalDateTime.now());
            
            // 如果管理员提供了extractedValue（步数/里程），更新verifySteps
            if (extractedValue != null && ("walk".equals(checkinRecord.getSceneType()) || "ride".equals(checkinRecord.getSceneType()))) {
                String updatedVerifySteps = updateVerifyStepsWithExtractedValue(
                        checkinRecord.getVerifySteps(), 
                        extractedValue
                );
                checkinRecord.setVerifySteps(updatedVerifySteps);
                log.info("管理员手动输入extractedValue: sceneType={}, extractedValue={}", checkinRecord.getSceneType(), extractedValue);
            }
            
            // 获取场景配置，确定基础奖励积分
            SceneConfig sceneConfig = sceneConfigRepository.findBySceneType(checkinRecord.getSceneType())
                    .orElse(null);
            int baseRewardPoints = sceneConfig != null ? sceneConfig.getRewardPoints() : 10;
            
            // 计算动态积分（如果支持）
            int rewardPoints = calculateDynamicRewardPoints(
                    checkinRecord.getSceneType(), 
                    checkinRecord.getVerifySteps(), 
                    baseRewardPoints
            );
            
            log.info("审核通过 - 积分计算完成: sceneType={}, baseRewardPoints={}, finalRewardPoints={}, verifySteps={}", 
                    checkinRecord.getSceneType(), baseRewardPoints, rewardPoints, checkinRecord.getVerifySteps());
            
            checkinRecord.setRewardPoints(rewardPoints);
            
            // 更新用户积分和统计（人工复核通过也算成功打卡一次，前端会根据统计判断是否可解锁勋章）
            User user = userRepository.findById(checkinRecord.getUserId())
                    .orElseThrow(() -> new BusinessException("用户不存在"));
            
            // 更新积分
            user.setPoints((user.getPoints() != null ? user.getPoints() : 0) + rewardPoints);
            
            // 更新打卡统计（人工复核通过时，增加对应场景的打卡次数）
            updateCheckinStatistics(user, checkinRecord.getSceneType(), true);
            
            // 保存用户信息
            userRepository.save(user);
            
            log.info("人工复核通过，用户统计已更新: userId={}, sceneType={}, rewardPoints={}, walkCheckins={}, plateCheckins={}, rideCheckins={}, transitCheckins={}, totalCheckins={}", 
                    checkinRecord.getUserId(), checkinRecord.getSceneType(), rewardPoints,
                    user.getWalkCheckins(), user.getPlateCheckins(), 
                    user.getRideCheckins(), user.getTransitCheckins(), 
                    user.getTotalCheckins());
            
            checkinRecordRepository.save(checkinRecord);
            
            // 创建审核通过通知（给用户）
            notificationService.createApproveNotification(
                    checkinRecord.getUserId(),
                    checkinRecord.getId(),
                    checkinRecord.getSceneType(),
                    rewardPoints
            );
        } else {
            // 人工复核驳回：不更新统计，不解锁勋章，更新打卡记录为已驳回
            checkinRecord.setStatus("REJECTED");
            checkinRecord.setVerifyReason(comment);
            checkinRecord.setVerifyTime(LocalDateTime.now());
            checkinRecordRepository.save(checkinRecord);
            
            // 审核驳回，说明用户可能存在作弊行为，增加可疑次数
            incrementSuspiciousCount(checkinRecord.getUserId());
            log.info("审核驳回，已增加用户可疑次数: userId={}, checkinId={}", checkinRecord.getUserId(), checkinRecord.getId());
            
            // 创建驳回通知（给用户）
            notificationService.createRejectNotification(
                    checkinRecord.getUserId(),
                    checkinRecord.getId(),
                    checkinRecord.getSceneType(),
                    comment
            );
        }
        
        // 构建响应
        ReviewDTO.ReviewActionResponse response = new ReviewDTO.ReviewActionResponse();
        response.setReviewId(reviewId);
        response.setAction(action);
        response.setMessage(action.equals("APPROVE") ? "审核通过，积分已发放" : "审核驳回");
        
        return response;
    }
    
    /**
     * 将ReviewRecord实体转换为ReviewRecordInfo DTO
     */
    private ReviewDTO.ReviewRecordInfo convertToReviewRecordInfo(ReviewRecord reviewRecord) {
        ReviewDTO.ReviewRecordInfo info = new ReviewDTO.ReviewRecordInfo();
        info.setId(reviewRecord.getId());
        info.setCheckinId(reviewRecord.getCheckinId());
        info.setUserId(reviewRecord.getUserId());
        
        // 获取用户信息
        User user = userRepository.findById(reviewRecord.getUserId())
                .orElse(null);
        if (user != null) {
            info.setName(user.getUsername() != null ? user.getUsername() : user.getNickname());
            info.setStudentId(user.getStudentId());
            info.setAvatar(user.getAvatar());
            // 生成头像背景色（基于姓名首字母）
            info.setAvatarBg(generateAvatarBg(user.getUsername() != null ? user.getUsername() : user.getNickname()));
        }
        
        // 场景信息
        info.setSceneType(reviewRecord.getSceneType());
        info.setScene(SCENE_TYPE_MAP.getOrDefault(reviewRecord.getSceneType(), reviewRecord.getSceneType()));
        
        // 获取场景图标
        SceneConfig sceneConfig = sceneConfigRepository.findBySceneType(reviewRecord.getSceneType())
                .orElse(null);
        info.setSceneIcon(sceneConfig != null ? sceneConfig.getIcon() : "📋");
        
        // 凭证图片
        info.setImageUrl(reviewRecord.getImageUrl());
        info.setEvidence(reviewRecord.getImageUrl());
        
        // 异常原因
        info.setReason(reviewRecord.getReason());
        info.setReasonType(reviewRecord.getReasonType());
        info.setReasonIcon(REASON_ICON_MAP.getOrDefault(reviewRecord.getReasonType(), "🟡"));
        info.setConfidence(reviewRecord.getConfidence());
        info.setAiReason(reviewRecord.getAiReason());
        
        // 提交时间
        if (reviewRecord.getSubmitTime() != null) {
            info.setSubmitDate(reviewRecord.getSubmitTime().format(DATE_FORMATTER));
            info.setSubmitTime(reviewRecord.getSubmitTime().format(TIME_FORMATTER));
            info.setSubmitDateTime(reviewRecord.getSubmitTime());
        }
        
        return info;
    }
    
    /**
     * 生成头像背景色（基于姓名）
     */
    private String generateAvatarBg(String name) {
        if (name == null || name.isEmpty()) {
            return "linear-gradient(135deg, #909399 0%, #606266 100%)";
        }
        
        // 根据姓名首字母生成不同的渐变色
        char firstChar = name.charAt(0);
        int index = firstChar % 5;
        
        String[] gradients = {
            "linear-gradient(135deg, #f56c6c 0%, #e64545 100%)", // 红色
            "linear-gradient(135deg, #e6a23c 0%, #d48806 100%)", // 橙色
            "linear-gradient(135deg, #909399 0%, #606266 100%)", // 灰色
            "linear-gradient(135deg, #7e57c2 0%, #5e35b1 100%)", // 紫色
            "linear-gradient(135deg, #409eff 0%, #337ecc 100%)"  // 蓝色
        };
        
        return gradients[index];
    }
    
    /**
     * 更新打卡统计
     */
    private void updateCheckinStatistics(User user, String sceneType, boolean increment) {
        int change = increment ? 1 : -1;
        
        switch (sceneType) {
            case "walk":
                user.setWalkCheckins((user.getWalkCheckins() != null ? user.getWalkCheckins() : 0) + change);
                break;
            case "plate":
                user.setPlateCheckins((user.getPlateCheckins() != null ? user.getPlateCheckins() : 0) + change);
                break;
            case "ride":
                user.setRideCheckins((user.getRideCheckins() != null ? user.getRideCheckins() : 0) + change);
                break;
            case "transit":
                user.setTransitCheckins((user.getTransitCheckins() != null ? user.getTransitCheckins() : 0) + change);
                break;
        }
        
        // 更新总打卡次数
        user.setTotalCheckins((user.getTotalCheckins() != null ? user.getTotalCheckins() : 0) + change);
    }
    
    /**
     * 根据OCR识别的数值计算动态积分
     * 
     * @param sceneType 场景类型
     * @param verifySteps 验证步骤详情（JSON字符串）
     * @param basePoints 基础积分
     * @return 计算后的积分
     */
    private Integer calculateDynamicRewardPoints(String sceneType, String verifySteps, Integer basePoints) {
        try {
            // 获取场景配置
            SceneConfig config = sceneConfigRepository.findBySceneType(sceneType).orElse(null);
            if (config == null) {
                return basePoints != null ? basePoints : 10;
            }
            
            // 基础积分（优先使用传入的参数，否则从配置获取）
            int finalBasePoints = basePoints != null ? basePoints : (config.getRewardPoints() != null ? config.getRewardPoints() : 10);
            
            // 只有walk和ride支持动态积分
            if (!"walk".equals(sceneType) && !"ride".equals(sceneType)) {
                return finalBasePoints;
            }
            
            // 如果没有配置bonus_step或bonus_percentage，返回基础积分
            if (config.getBonusStep() == null || config.getBonusPercentage() == null) {
                return finalBasePoints;
            }
            
            // 从verifySteps中提取extracted_value
            Double extractedValue = extractValueFromVerifySteps(verifySteps);
            if (extractedValue == null) {
                // 如果无法提取数值，返回基础积分
                log.warn("无法从verifySteps中提取extracted_value，返回基础积分: verifySteps={}", verifySteps);
                return finalBasePoints;
            }
            
            // 获取最低要求值（如果未配置，默认为0，表示所有步数都参与奖励计算）
            BigDecimal minValue = config.getMinValue();
            if (minValue == null) {
                minValue = BigDecimal.ZERO;
                log.info("minValue未配置，使用默认值0");
            }
            
            // 计算超出基础值的部分
            BigDecimal excessValue = BigDecimal.valueOf(extractedValue).subtract(minValue);
            if (excessValue.compareTo(BigDecimal.ZERO) <= 0) {
                // 没有超出，返回基础积分
                log.info("步数未超过最低要求值，返回基础积分: extractedValue={}, minValue={}", extractedValue, minValue);
                return finalBasePoints;
            }
            
            // 计算奖励倍数（每达到bonus_step增加bonus_percentage%）
            BigDecimal bonusStep = config.getBonusStep();
            BigDecimal bonusPercentage = config.getBonusPercentage();
            
            // 计算有多少个bonus_step（向下取整）
            BigDecimal bonusMultiplier = excessValue.divide(bonusStep, 2, java.math.RoundingMode.DOWN);
            int bonusCount = bonusMultiplier.intValue();
            
            // 计算总积分 = 基础积分 * (1 + bonusCount * bonusPercentage / 100)
            BigDecimal totalMultiplier = BigDecimal.ONE.add(
                BigDecimal.valueOf(bonusCount).multiply(bonusPercentage).divide(BigDecimal.valueOf(100), 2, java.math.RoundingMode.HALF_UP)
            );
            
            int finalPoints = BigDecimal.valueOf(finalBasePoints)
                    .multiply(totalMultiplier)
                    .setScale(0, java.math.RoundingMode.HALF_UP)
                    .intValue();
            
            log.info("动态积分计算详情: sceneType={}, basePoints={}, extractedValue={}, minValue={}, excessValue={}, bonusStep={}, bonusCount={}, bonusPercentage={}%, totalMultiplier={}, finalPoints={}", 
                    sceneType, finalBasePoints, extractedValue, minValue, excessValue, bonusStep, bonusCount, bonusPercentage, totalMultiplier, finalPoints);
            
            return finalPoints;
            
        } catch (Exception e) {
            log.error("计算动态积分失败: sceneType={}", sceneType, e);
            // 如果计算失败，返回基础积分
            return basePoints != null ? basePoints : 10;
        }
    }
    
    /**
     * 从verifySteps JSON字符串中提取extracted_value
     * 优先从OCR Check步骤提取，如果没有则从VLLM Check步骤提取
     * 
     * @param verifySteps 验证步骤详情（JSON字符串）
     * @return 提取的数值，如果无法提取则返回null
     */
    private Double extractValueFromVerifySteps(String verifySteps) {
        if (verifySteps == null || verifySteps.trim().isEmpty()) {
            return null;
        }
        
        try {
            // 解析JSON数组
            List<Map<String, Object>> steps = objectMapper.readValue(verifySteps, 
                    new TypeReference<List<Map<String, Object>>>() {});
            
            Double ocrValue = null;
            Double vllmValue = null;
            Double manualValue = null;
            
            // 遍历所有步骤，查找extracted_value
            for (Map<String, Object> step : steps) {
                String stepName = (String) step.get("step");
                
                // 检查是否有extracted_value字段
                Object extractedValue = step.get("extracted_value");
                Double stepValue = null;
                
                if (extractedValue != null) {
                    if (extractedValue instanceof Number) {
                        stepValue = ((Number) extractedValue).doubleValue();
                    } else if (extractedValue instanceof String) {
                        try {
                            stepValue = Double.parseDouble((String) extractedValue);
                        } catch (NumberFormatException e) {
                            // 忽略
                        }
                    }
                }
                
                // 优先从OCR Check步骤提取
                if (("OCR Check".equals(stepName) || "ocr_check".equals(stepName) || "OCR".equals(stepName)) && stepValue != null) {
                    ocrValue = stepValue;
                    log.info("从OCR Check步骤提取到extracted_value: {}", ocrValue);
                }
                // 如果没有OCR值，尝试从VLLM Check/AI步骤提取
                else if (("VLLM Check".equals(stepName) || "vllm_check".equals(stepName) || "AI".equals(stepName) || "AI Check".equals(stepName)) && stepValue != null) {
                    vllmValue = stepValue;
                    log.info("从AI/VLLM Check步骤提取到extracted_value: {}", vllmValue);
                }
                // 如果没有OCR和VLLM值，尝试从Manual Review步骤提取（管理员手动输入）
                else if (("Manual Review".equals(stepName) || "manual_review".equals(stepName)) && stepValue != null) {
                    manualValue = stepValue;
                    log.info("从Manual Review步骤提取到extracted_value: {}", manualValue);
                }
                
                // 如果都没有extracted_value字段，尝试从reason字段中提取数值（备用方案）
                if (stepValue == null && ("OCR Check".equals(stepName) || "ocr_check".equals(stepName))) {
                    String reason = (String) step.get("reason");
                    if (reason != null) {
                        // 尝试从reason中提取数字（如"步数: 8000"）
                        java.util.regex.Pattern pattern = java.util.regex.Pattern.compile("(\\d+\\.?\\d*)");
                        java.util.regex.Matcher matcher = pattern.matcher(reason);
                        if (matcher.find()) {
                            try {
                                ocrValue = Double.parseDouble(matcher.group(1));
                                log.info("从OCR Check步骤的reason字段提取到extracted_value: {}", ocrValue);
                            } catch (NumberFormatException e) {
                                // 忽略
                            }
                        }
                    }
                }
            }
            
            // 优先返回OCR提取的值，如果没有则返回VLLM提取的值，最后返回Manual Review的值
            if (ocrValue != null) {
                return ocrValue;
            } else if (vllmValue != null) {
                return vllmValue;
            } else if (manualValue != null) {
                return manualValue;
            }
            
            return null;
        } catch (Exception e) {
            log.warn("从verifySteps中提取extracted_value失败: {}", verifySteps, e);
            return null;
        }
    }
    
    /**
     * 更新verifySteps，添加或更新extracted_value
     * 
     * @param verifySteps 原始verifySteps JSON字符串
     * @param extractedValue 提取的数值（步数/里程）
     * @return 更新后的verifySteps JSON字符串
     */
    private String updateVerifyStepsWithExtractedValue(String verifySteps, Double extractedValue) {
        try {
            if (verifySteps == null || verifySteps.trim().isEmpty()) {
                // 如果verifySteps为空，创建一个新的步骤数组
                List<Map<String, Object>> steps = new java.util.ArrayList<>();
                Map<String, Object> manualStep = new HashMap<>();
                manualStep.put("step", "Manual Review");
                manualStep.put("status", "APPROVED");
                manualStep.put("reason", "管理员审核通过");
                manualStep.put("extracted_value", extractedValue);
                steps.add(manualStep);
                return objectMapper.writeValueAsString(steps);
            }
            
            // 解析现有的verifySteps
            List<Map<String, Object>> steps = objectMapper.readValue(verifySteps, 
                    new TypeReference<List<Map<String, Object>>>() {});
            
            // 查找是否已有OCR Check或VLLM Check步骤，如果有则更新extracted_value
            boolean found = false;
            for (Map<String, Object> step : steps) {
                String stepName = (String) step.get("step");
                if ("OCR Check".equals(stepName) || "ocr_check".equals(stepName) || 
                    "VLLM Check".equals(stepName) || "vllm_check".equals(stepName)) {
                    step.put("extracted_value", extractedValue);
                    found = true;
                    log.info("更新现有步骤的extracted_value: stepName={}, extractedValue={}", stepName, extractedValue);
                    break;
                }
            }
            
            // 如果没有找到OCR或VLLM步骤，添加一个新的手动审核步骤
            if (!found) {
                Map<String, Object> manualStep = new HashMap<>();
                manualStep.put("step", "Manual Review");
                manualStep.put("status", "APPROVED");
                manualStep.put("reason", "管理员审核通过，手动输入数值");
                manualStep.put("extracted_value", extractedValue);
                steps.add(manualStep);
                log.info("添加新的手动审核步骤，extractedValue={}", extractedValue);
            }
            
            return objectMapper.writeValueAsString(steps);
        } catch (Exception e) {
            log.error("更新verifySteps失败: verifySteps={}, extractedValue={}", verifySteps, extractedValue, e);
            // 如果更新失败，返回原始值
            return verifySteps;
        }
    }
    
    /**
     * 增加用户可疑次数
     * 
     * @param userId 用户ID
     */
    private void incrementSuspiciousCount(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在: " + userId));
        
        user.setSuspiciousCount((user.getSuspiciousCount() != null ? user.getSuspiciousCount() : 0) + 1);
        
        // 根据可疑次数更新风险等级（统一判断逻辑：suspiciousCount > 0 就设为 SUSPICIOUS）
        Integer suspiciousCount = user.getSuspiciousCount();
        if (suspiciousCount >= 5) {
            user.setRiskLevel("HIGH");
        } else if (suspiciousCount > 0) {
            user.setRiskLevel("SUSPICIOUS");
        } else {
            user.setRiskLevel("SAFE");
        }
        
        userRepository.save(user);
        
        log.info("用户可疑次数更新: userId={}, suspiciousCount={}, riskLevel={}", 
                userId, suspiciousCount, user.getRiskLevel());
    }
}

