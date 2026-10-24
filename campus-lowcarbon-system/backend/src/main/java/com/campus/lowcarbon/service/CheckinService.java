/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.entity.CheckinRecord;
import com.campus.lowcarbon.entity.CheckinLocation;
import com.campus.lowcarbon.entity.ReviewRecord;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.repository.CheckinRecordRepository;
import com.campus.lowcarbon.repository.CheckinLocationRepository;
import com.campus.lowcarbon.repository.ReviewRecordRepository;
import com.campus.lowcarbon.repository.SceneConfigRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.campus.lowcarbon.entity.SceneConfig;

/**
 * 类
 * 处理打卡记录保存、积分更新、统计更新等业务逻辑
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class CheckinService {
    
    private final CheckinRecordRepository checkinRecordRepository;
    private final CheckinLocationRepository checkinLocationRepository;
    private final UserRepository userRepository;
    private final SceneConfigRepository sceneConfigRepository;
    private final ReviewRecordRepository reviewRecordRepository;
    private final NotificationService notificationService;
    
    @Value("${file.upload.path:uploads}")
    private String uploadPath;
    
    @Value("${file.upload.url-prefix:/api/uploads}")
    private String urlPrefix;
    
    private final ObjectMapper objectMapper = new ObjectMapper();
    
    /**
     * 保存打卡记录
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param imageFile 图片文件
     * @param status 验证状态（APPROVED/REJECTED/SUSPICIOUS）
     * @param verifyReason 验证原因
     * @param verifySteps 验证步骤详情（JSON字符串）
     * @param imageHash 图片MD5哈希值
     * @param rewardPoints 奖励积分（仅当status=APPROVED时有效）
     * @param locationId 定位记录ID（可选，如果使用了定位功能）
     * @return 打卡记录ID
     */
    @Transactional
    public Long saveCheckinRecord(
            Long userId,
            String sceneType,
            MultipartFile imageFile,
            String status,
            String verifyReason,
            String verifySteps,
            String imageHash,
            Integer rewardPoints,
            Long locationId) {
        
        try {
            // 1. 检查是否有待更新的打卡记录（通过locationId查找）
            // 注意：次数限制检查已提前在用户上传图片或点击开始打卡时进行，这里不再重复检查
            CheckinRecord record = null;
            
            if (locationId != null) {
                // 查找定位记录
                CheckinLocation location = checkinLocationRepository.findById(locationId).orElse(null);
                if (location != null && location.getCheckinId() != null) {
                    // 如果定位记录已有关联的打卡记录，说明次数已在结束打卡时消耗，更新现有记录
                    record = checkinRecordRepository.findById(location.getCheckinId()).orElse(null);
                    if (record != null && "PENDING".equals(record.getStatus()) && record.getImageUrl() == null) {
                        // 找到待提交的记录，更新它而不是创建新记录
                        log.info("找到待提交的打卡记录，将更新现有记录: recordId={}, locationId={}", record.getId(), locationId);
                    }
                }
            }
            
            // 3. 计算图片MD5哈希值（如果未提供）
            String finalImageHash = imageHash;
            if (finalImageHash == null || finalImageHash.trim().isEmpty()) {
                finalImageHash = calculateImageMD5(imageFile);
            }
            
            // 4. 检查图片是否重复（按场景类型检测）
            checkDuplicateImage(finalImageHash, sceneType);
            
            // 5. 计算动态积分（如果通过验证）
            Integer finalRewardPoints = rewardPoints;
            if ("APPROVED".equals(status)) {
                // 后端重新计算动态积分，使用配置中的基础积分（而不是前端传递的rewardPoints）
                // 因为前端传递的rewardPoints是AI服务已经计算好的最终积分，不应该作为基础积分再次计算
                finalRewardPoints = calculateDynamicRewardPoints(sceneType, verifySteps, null);
            }
            
            // 6. 保存图片文件（使用MD5作为文件名，相同MD5的图片复用同一文件）
            String imageUrl = saveImageFile(imageFile, sceneType, finalImageHash);
            
            // 7. 创建或更新打卡记录
            if (record == null) {
                // 创建新记录
                record = new CheckinRecord();
                record.setUserId(userId);
                record.setSceneType(sceneType);
                record.setSubmitTime(LocalDateTime.now());
            }
            
            // 更新记录字段
            record.setImageUrl(imageUrl);
            record.setImageHash(finalImageHash);
            record.setStatus(status);
            record.setVerifyReason(verifyReason);
            record.setVerifySteps(verifySteps);
            
            // 如果通过验证，设置奖励积分和审核时间
            if ("APPROVED".equals(status)) {
                record.setRewardPoints(finalRewardPoints != null ? finalRewardPoints : 0);
                record.setVerifyTime(LocalDateTime.now());
            } else if ("SUSPICIOUS".equals(status)) {
                // 可疑状态，不设置审核时间，等待人工审核
                record.setRewardPoints(0);
            } else if ("REJECTED".equals(status)) {
                // AI自动驳回状态，设置审核时间
                record.setRewardPoints(0);
                record.setVerifyTime(LocalDateTime.now());
            } else {
                // 其他拒绝状态
                record.setRewardPoints(0);
            }
            
            // 8. 保存打卡记录
            CheckinRecord savedRecord = checkinRecordRepository.save(record);
            
            // 9. 如果提供了定位记录ID，关联定位记录到打卡记录（如果还没有关联）
            if (locationId != null) {
                CheckinLocation location = checkinLocationRepository.findById(locationId).orElse(null);
                if (location != null && location.getCheckinId() == null) {
                    location.setCheckinId(savedRecord.getId());
                    checkinLocationRepository.save(location);
                }
            }
            
            // 7. 根据审核结果处理用户统计
            if ("APPROVED".equals(status)) {
                // AI自动审核通过：更新用户积分和统计（前端会根据统计判断是否可解锁勋章）
                updateUserPointsAndStats(userId, sceneType, finalRewardPoints != null ? finalRewardPoints : 0);
                
                // 创建审核记录用于统计（AI自动通过，reviewer_id为NULL）
                log.info("AI自动审核通过，创建审核记录: checkinId={}, userId={}, sceneType={}", 
                        savedRecord.getId(), userId, sceneType);
                createReviewRecord(savedRecord.getId(), userId, sceneType, imageUrl, "AI自动审核通过", "APPROVED", null);
            } else if ("SUSPICIOUS".equals(status)) {
                // 可疑状态：不更新统计，不解锁勋章，等待人工复核
                // 可疑状态，判断是否为AI服务断链
                boolean isAiDown = isAiServiceDown(verifyReason);
                
                // 只有非AI服务断链的情况才增加可疑次数
                // AI服务断链导致的SUSPICIOUS，等待管理员审核后再决定是否增加可疑次数
                if (!isAiDown) {
                    incrementSuspiciousCount(userId);
                    log.info("非AI服务断链导致的SUSPICIOUS，已增加可疑次数: userId={}, verifyReason={}", userId, verifyReason);
                } else {
                    log.info("AI服务断链导致的SUSPICIOUS，不增加可疑次数，等待管理员审核: userId={}, verifyReason={}", userId, verifyReason);
                }
                
                // 创建审核记录，转入人工复核池
                createReviewRecord(savedRecord.getId(), userId, sceneType, imageUrl, verifyReason, "PENDING", null);
                
                // 创建人工复核通知（给所有管理员）
                User user = userRepository.findById(userId).orElse(null);
                String userName = user != null ? user.getUsername() : "未知用户";
                notificationService.createReviewNotification(savedRecord.getId(), userId, sceneType, userName);
                
                // 创建转入人工复核通知（给用户）
                notificationService.createReviewPendingNotification(userId, savedRecord.getId(), sceneType);
            } else if ("REJECTED".equals(status)) {
                // AI自动驳回：不更新统计，不解锁勋章，创建审核记录用于统计
                createReviewRecord(savedRecord.getId(), userId, sceneType, imageUrl, verifyReason, "REJECTED", null);
            }
            
            log.info("打卡记录保存成功: userId={}, sceneType={}, status={}, recordId={}, rewardPoints={}", 
                    userId, sceneType, status, savedRecord.getId(), finalRewardPoints);
            
            return savedRecord.getId();
            
        } catch (Exception e) {
            log.error("保存打卡记录失败: userId={}, sceneType={}", userId, sceneType, e);
            throw new RuntimeException("保存打卡记录失败: " + e.getMessage(), e);
        }
    }
    
    /**
     * 获取打卡记录的实际积分
     * 
     * @param recordId 打卡记录ID
     * @return 实际积分，如果记录不存在则返回null
     */
    public Integer getCheckinRecordRewardPoints(Long recordId) {
        return checkinRecordRepository.findById(recordId)
                .map(CheckinRecord::getRewardPoints)
                .orElse(null);
    }
    
    /**
     * 计算图片的MD5哈希值
     * 
     * @param imageFile 图片文件
     * @return MD5哈希值（32位十六进制字符串）
     */
    private String calculateImageMD5(MultipartFile imageFile) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            try (InputStream is = imageFile.getInputStream()) {
                byte[] buffer = new byte[8192];
                int bytesRead;
                while ((bytesRead = is.read(buffer)) != -1) {
                    md.update(buffer, 0, bytesRead);
                }
            }
            byte[] digest = md.digest();
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            log.error("计算图片MD5失败", e);
            throw new RuntimeException("计算图片MD5失败: " + e.getMessage(), e);
        }
    }
    
    /**
     * 检查图片是否重复（按场景类型检测）
     * 
     * @param imageHash 图片MD5哈希值
     * @param sceneType 场景类型
     * @throws RuntimeException 如果图片重复
     */
    private void checkDuplicateImage(String imageHash, String sceneType) {
        if (imageHash == null || imageHash.trim().isEmpty()) {
            return; // 如果没有哈希值，跳过检查
        }
        
        List<CheckinRecord> existingRecords = checkinRecordRepository.findByImageHashAndSceneType(imageHash, sceneType);
        if (!existingRecords.isEmpty()) {
            log.warn("检测到重复图片: imageHash={}, sceneType={}, existingCount={}", 
                    imageHash, sceneType, existingRecords.size());
            throw new RuntimeException("重复提交：该图片已在" + getSceneTypeName(sceneType) + "项目中使用过");
        }
    }
    
    /**
     * 获取场景类型的中文名称
     * 
     * @param sceneType 场景类型
     * @return 中文名称
     */
    private String getSceneTypeName(String sceneType) {
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
                return sceneType;
        }
    }
    
    /**
     * 保存图片文件（使用MD5作为文件名，相同MD5的图片复用同一文件）
     * 
     * @param imageFile 图片文件
     * @param sceneType 场景类型
     * @param imageHash 图片MD5哈希值
     * @return 图片访问URL
     */
    private String saveImageFile(MultipartFile imageFile, String sceneType, String imageHash) throws IOException {
        // 创建上传目录（按场景类型分类）
        Path uploadBasePath = Paths.get(uploadPath).toAbsolutePath();
        Path sceneDir = uploadBasePath.resolve("checkin").resolve(sceneType);
        if (!Files.exists(sceneDir)) {
            Files.createDirectories(sceneDir);
        }
        
        // 获取文件扩展名
        String originalFilename = imageFile.getOriginalFilename();
        String extension = "";
        if (originalFilename != null && originalFilename.contains(".")) {
            extension = originalFilename.substring(originalFilename.lastIndexOf("."));
        }
        
        // 使用MD5作为文件名的一部分，相同MD5的图片使用同一个文件
        // 格式：{MD5前8位}_{完整MD5}.扩展名
        // 这样既能通过MD5识别，又能通过前8位快速查找
        String hashPrefix = imageHash != null && imageHash.length() >= 8 ? imageHash.substring(0, 8) : "unknown";
        String filename = hashPrefix + "_" + imageHash + extension;
        
        // 检查文件是否已存在
        Path filePath = sceneDir.resolve(filename);
        if (!Files.exists(filePath)) {
            // 文件不存在，保存新文件
        imageFile.transferTo(filePath.toFile());
            log.info("保存新图片文件: sceneType={}, filename={}, md5={}", sceneType, filename, imageHash);
        } else {
            // 文件已存在，复用现有文件（节省存储空间）
            log.info("复用已存在的图片文件: sceneType={}, filename={}, md5={}", sceneType, filename, imageHash);
        }
        
        // 生成访问URL
        String fileUrl = (urlPrefix.startsWith("/") ? "" : "/") + urlPrefix + "/checkin/" + sceneType + "/" + filename;
        
        return fileUrl;
    }
    
    /**
     * 更新用户积分和统计
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param rewardPoints 奖励积分
     */
    private void updateUserPointsAndStats(Long userId, String sceneType, Integer rewardPoints) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("用户不存在: " + userId));
        
        // 更新积分
        user.setPoints((user.getPoints() != null ? user.getPoints() : 0) + rewardPoints);
        
        // 更新统计字段
        switch (sceneType) {
            case "walk":
                user.setWalkCheckins((user.getWalkCheckins() != null ? user.getWalkCheckins() : 0) + 1);
                break;
            case "ride":
                user.setRideCheckins((user.getRideCheckins() != null ? user.getRideCheckins() : 0) + 1);
                break;
            case "plate":
                user.setPlateCheckins((user.getPlateCheckins() != null ? user.getPlateCheckins() : 0) + 1);
                break;
            case "transit":
                user.setTransitCheckins((user.getTransitCheckins() != null ? user.getTransitCheckins() : 0) + 1);
                break;
        }
        
        // 更新总打卡次数
        user.setTotalCheckins((user.getTotalCheckins() != null ? user.getTotalCheckins() : 0) + 1);
        
        userRepository.save(user);
        
        log.info("用户积分和统计更新成功: userId={}, sceneType={}, rewardPoints={}", 
                userId, sceneType, rewardPoints);
    }
    
    /**
     * 增加用户可疑次数
     * 
     * @param userId 用户ID
     */
    private void incrementSuspiciousCount(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("用户不存在: " + userId));
        
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
    
    /**
     * 判断是否为AI服务断链导致的SUSPICIOUS状态
     * 
     * @param verifyReason 验证原因
     * @return true表示是AI服务断链，false表示其他原因
     */
    private boolean isAiServiceDown(String verifyReason) {
        if (verifyReason == null || verifyReason.trim().isEmpty()) {
            return false;
        }
        String reasonLower = verifyReason.toLowerCase();
        return reasonLower.contains("ai服务") || reasonLower.contains("ai服务断链") 
                || reasonLower.contains("ai服务不可用") || reasonLower.contains("调用失败")
                || reasonLower.contains("ai服务断链") || reasonLower.contains("ai视觉模型调用失败");
    }
    
    /**
     * 创建审核记录
     * 
     * @param checkinId 打卡记录ID
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param imageUrl 图片URL
     * @param verifyReason 验证原因
     * @param reviewStatus 审核状态（PENDING-待处理，REJECTED-已驳回）
     * @param reviewerId 审核人ID（NULL表示AI自动处理）
     */
    private void createReviewRecord(Long checkinId, Long userId, String sceneType, 
                                   String imageUrl, String verifyReason, 
                                   String reviewStatus, Long reviewerId) {
        try {
            ReviewRecord reviewRecord = new ReviewRecord();
            reviewRecord.setCheckinId(checkinId);
            reviewRecord.setUserId(userId);
            reviewRecord.setSceneType(sceneType);
            reviewRecord.setImageUrl(imageUrl);
            reviewRecord.setReviewStatus(reviewStatus);
            reviewRecord.setReviewerId(reviewerId);
            reviewRecord.setSubmitTime(LocalDateTime.now());
            
            // 如果是REJECTED或APPROVED状态，设置review_time用于统计
            if ("REJECTED".equals(reviewStatus) || "APPROVED".equals(reviewStatus)) {
                reviewRecord.setReviewTime(LocalDateTime.now());
            }
            
            // 设置异常原因
            if (verifyReason != null && !verifyReason.trim().isEmpty()) {
                reviewRecord.setReason(verifyReason);
                
                // 根据原因判断reasonType
                String reasonLower = verifyReason.toLowerCase();
                if (reasonLower.contains("ai服务") || reasonLower.contains("ai服务断链") 
                    || reasonLower.contains("ai服务不可用") || reasonLower.contains("调用失败")) {
                    // AI服务断链或调用失败，标记为warning
                    reviewRecord.setReasonType("warning");
                    reviewRecord.setAiReason("AI服务不可用或调用失败，需要人工审核");
                } else if (reasonLower.contains("不确定") || reasonLower.contains("存疑")) {
                    // AI不确定，标记为warning
                    reviewRecord.setReasonType("warning");
                    reviewRecord.setAiReason(verifyReason);
                } else if (reasonLower.contains("ai判定") || reasonLower.contains("不通过") 
                    || reasonLower.contains("拒绝") || reasonLower.contains("驳回")) {
                    // AI判定不通过，标记为danger
                    reviewRecord.setReasonType("danger");
                    reviewRecord.setAiReason(verifyReason);
                } else {
                    // 其他情况，默认标记为info
                    reviewRecord.setReasonType("info");
                    reviewRecord.setAiReason(verifyReason);
                }
            } else {
                // 如果没有原因，使用默认值
                if ("REJECTED".equals(reviewStatus)) {
                    reviewRecord.setReason("AI自动驳回");
                    reviewRecord.setReasonType("danger");
                } else {
                    reviewRecord.setReason("需要人工审核");
                    reviewRecord.setReasonType("info");
                }
            }
            
            // 设置置信度
            if ("REJECTED".equals(reviewStatus)) {
                // AI自动驳回，置信度设为80（较高）
                reviewRecord.setConfidence(80);
            } else {
                // AI服务断链或不确定，置信度设为50（中等风险）
                reviewRecord.setConfidence(50);
            }
            
            reviewRecordRepository.save(reviewRecord);
            
            log.info("审核记录创建成功: checkinId={}, userId={}, sceneType={}, reviewStatus={}, reviewId={}", 
                    checkinId, userId, sceneType, reviewStatus, reviewRecord.getId());
                    
        } catch (Exception e) {
            log.error("创建审核记录失败: checkinId={}, userId={}, sceneType={}, reviewStatus={}", 
                    checkinId, userId, sceneType, reviewStatus, e);
            // 不抛出异常，避免影响打卡记录的保存
        }
    }
    
    /**
     * 检查每日打卡次数限制
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @throws RuntimeException 如果超过每日打卡次数限制
     */
    public void checkDailyLimit(Long userId, String sceneType) {
        SceneConfig config = sceneConfigRepository.findBySceneType(sceneType).orElse(null);
        if (config == null || config.getDailyLimit() == null || config.getDailyLimit() == 0) {
            // 如果没有配置或限制为0，表示不限制
            return;
        }
        
        int dailyLimit = config.getDailyLimit();
        
        // 获取今天的开始和结束时间
        LocalDate today = LocalDate.now();
        LocalDateTime todayStart = today.atStartOfDay(); // 00:00:00
        LocalDateTime todayEnd = today.plusDays(1).atStartOfDay(); // 明天的00:00:00（用于<判断）
        
        // 统计用户今天该场景的打卡次数（包括所有状态：PENDING、APPROVED、REJECTED、SUSPICIOUS）
        // 使用数据库查询，效率更高
        long todayCount = checkinRecordRepository.countTodayCheckinsByUserAndSceneType(
                userId, sceneType, todayStart, todayEnd);
        
        log.info("检查每日打卡次数限制: userId={}, sceneType={}, todayCount={}, dailyLimit={}", 
                userId, sceneType, todayCount, dailyLimit);
        
        if (todayCount >= dailyLimit) {
            String sceneName = getSceneTypeName(sceneType);
            throw new RuntimeException(String.format("今日%s打卡次数已达上限（%d次），请明天再试", sceneName, dailyLimit));
        }
    }
    
    /**
     * 根据OCR识别的数值计算动态积分
     * 
     * @param sceneType 场景类型
     * @param verifySteps 验证步骤详情（JSON字符串）
     * @param basePoints 基础积分（如果为null，则从配置中获取）
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
                return basePoints;
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
            // 例如：基础积分10，bonusCount=9，bonusPercentage=100%
            // 总积分 = 10 * (1 + 9 * 100 / 100) = 10 * (1 + 9) = 10 * 10 = 100
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
            if (basePoints != null) {
                return basePoints;
            }
            SceneConfig config = sceneConfigRepository.findBySceneType(sceneType).orElse(null);
            return config != null && config.getRewardPoints() != null ? config.getRewardPoints() : 10;
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
            
            // 优先返回OCR提取的值，如果没有则返回VLLM提取的值
            if (ocrValue != null) {
                return ocrValue;
            } else if (vllmValue != null) {
                return vllmValue;
            }
            
            return null;
        } catch (Exception e) {
            log.warn("从verifySteps中提取extracted_value失败: {}", verifySteps, e);
            return null;
        }
    }
}

