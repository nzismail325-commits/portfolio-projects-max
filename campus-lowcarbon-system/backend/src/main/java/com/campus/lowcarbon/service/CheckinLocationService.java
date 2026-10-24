/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.entity.CheckinLocation;
import com.campus.lowcarbon.entity.CheckinRecord;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.CheckinLocationRepository;
import com.campus.lowcarbon.repository.CheckinRecordRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 打卡位置服务类
 * 处理定位相关的业务逻辑，包括百度地图API调用
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class CheckinLocationService {
    
    private final CheckinLocationRepository checkinLocationRepository;
    private final UserRepository userRepository;
    private final CheckinRecordRepository checkinRecordRepository;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();
    
    @Value("${baidu.map.api.key:}")
    private String baiduMapApiKey;
    
    /**
     * 开始打卡（记录起始位置）
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param latitude 纬度
     * @param longitude 经度
     * @return 定位记录ID
     */
    @Transactional
    public Long startCheckinLocation(Long userId, String sceneType, BigDecimal latitude, BigDecimal longitude) {
        // 检查用户是否存在
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 检查是否已有进行中的定位记录（同一场景类型）
        Optional<CheckinLocation> existingLocation = checkinLocationRepository
                .findFirstByUserIdAndSceneTypeAndStatusOrderByStartTimeDesc(userId, sceneType, "IN_PROGRESS");
        
        if (existingLocation.isPresent()) {
            // 如果存在进行中的记录，先取消它
            CheckinLocation oldLocation = existingLocation.get();
            oldLocation.setStatus("CANCELLED");
            checkinLocationRepository.save(oldLocation);
            log.info("取消用户进行中的定位记录: userId={}, sceneType={}, locationId={}", 
                    userId, sceneType, oldLocation.getId());
        }
        
        // 通过百度API获取地址（逆地理编码）
        String address = getAddressFromBaiduAPI(latitude, longitude);
        
        // 创建新的定位记录
        CheckinLocation location = new CheckinLocation();
        location.setUserId(userId);
        location.setSceneType(sceneType);
        location.setStartLatitude(latitude);
        location.setStartLongitude(longitude);
        location.setStartAddress(address);
        location.setStartTime(LocalDateTime.now());
        location.setStatus("IN_PROGRESS");
        
        CheckinLocation savedLocation = checkinLocationRepository.save(location);
        
        log.info("创建定位记录成功: userId={}, sceneType={}, locationId={}, startLat={}, startLng={}", 
                userId, sceneType, savedLocation.getId(), latitude, longitude);
        
        return savedLocation.getId();
    }
    
    /**
     * 结束打卡（记录结束位置并计算距离）
     * 
     * @param locationId 定位记录ID
     * @param latitude 纬度
     * @param longitude 经度
     * @return 距离（米）和状态信息
     */
    @Transactional
    public Map<String, Object> endCheckinLocation(Long locationId, BigDecimal latitude, BigDecimal longitude) {
        // 查找定位记录
        CheckinLocation location = checkinLocationRepository.findById(locationId)
                .orElseThrow(() -> new BusinessException("定位记录不存在"));
        
        // 检查状态
        if (!"IN_PROGRESS".equals(location.getStatus())) {
            throw new BusinessException("定位记录状态不正确，无法结束打卡");
        }
        
        // 通过百度API获取地址（逆地理编码）
        String address = getAddressFromBaiduAPI(latitude, longitude);
        
        // 更新结束位置信息
        location.setEndLatitude(latitude);
        location.setEndLongitude(longitude);
        location.setEndAddress(address);
        location.setEndTime(LocalDateTime.now());
        
        // 使用百度API计算距离
        BigDecimal distance = calculateDistanceFromBaiduAPI(
                location.getStartLatitude(), 
                location.getStartLongitude(),
                latitude,
                longitude
        );
        
        location.setDistance(distance);
        
        Map<String, Object> result = new HashMap<>();
        
        // 判断距离是否满足要求（1公里 = 1000米）
        if (distance.compareTo(new BigDecimal("1000")) < 0) {
            // 距离小于1公里，增加用户可疑次数并消耗打卡次数
            User user = userRepository.findById(location.getUserId())
                    .orElseThrow(() -> new BusinessException("用户不存在"));
            
            // 增加可疑次数
            user.setSuspiciousCount((user.getSuspiciousCount() != null ? user.getSuspiciousCount() : 0) + 1);
            
            // 更新风险等级
            Integer suspiciousCount = user.getSuspiciousCount();
            if (suspiciousCount >= 5) {
                user.setRiskLevel("HIGH");
            } else if (suspiciousCount > 0) {
                user.setRiskLevel("SUSPICIOUS");
            }
            
            userRepository.save(user);
            
            // 更新定位记录状态为已取消（因为距离不足）
            location.setStatus("CANCELLED");
            checkinLocationRepository.save(location);
            
            // 消耗一次打卡次数（通过创建一个失败的打卡记录来实现）
            consumeCheckinCount(location.getUserId(), location.getSceneType());
            
            result.put("distance", distance);
            result.put("status", "FAILED");
            result.put("message", "距离太近，请不要作弊，真正出行");
            
            log.warn("定位打卡距离不足: userId={}, sceneType={}, locationId={}, distance={}m", 
                    location.getUserId(), location.getSceneType(), locationId, distance);
        } else {
            // 距离满足要求，更新状态为已完成
            location.setStatus("COMPLETED");
            checkinLocationRepository.save(location);
            
            // 消耗一次打卡次数（通过创建一个待提交的打卡记录来实现）
            // 这个记录会在用户提交图片时被更新，而不是创建新记录
            Long pendingRecordId = consumeCheckinCountForCompleted(location.getUserId(), location.getSceneType(), locationId);
            
            result.put("distance", distance);
            result.put("status", "SUCCESS");
            result.put("message", "定位打卡成功");
            result.put("pendingRecordId", pendingRecordId); // 返回待提交的记录ID，前端可以用于后续提交
            
            log.info("定位打卡成功: userId={}, sceneType={}, locationId={}, distance={}m, pendingRecordId={}", 
                    location.getUserId(), location.getSceneType(), locationId, distance, pendingRecordId);
        }
        
        return result;
    }
    
    /**
     * 消耗一次打卡次数（通过创建一个失败的打卡记录）
     * 根据需求，即使距离不足导致失败，也要消耗一次打卡次数
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     */
    private void consumeCheckinCount(Long userId, String sceneType) {
        // 创建一个状态为REJECTED的打卡记录，标记为"定位失败"
        // 这样可以消耗打卡次数，符合业务需求
        CheckinRecord record = new CheckinRecord();
        record.setUserId(userId);
        record.setSceneType(sceneType);
        record.setImageUrl(null); // 无图片
        record.setImageHash(null);
        record.setStatus("REJECTED");
        record.setRewardPoints(0);
        record.setVerifyReason("定位打卡距离不足1公里，打卡失败");
        record.setVerifySteps("[]"); // 空的验证步骤
        record.setSubmitTime(LocalDateTime.now());
        record.setVerifyTime(LocalDateTime.now());
        
        checkinRecordRepository.save(record);
        
        log.info("创建定位失败打卡记录，消耗打卡次数: userId={}, sceneType={}, recordId={}", 
                userId, sceneType, record.getId());
    }
    
    /**
     * 消耗一次打卡次数（通过创建一个待提交的打卡记录）
     * 当距离满足要求时，创建一个PENDING状态的记录，等待用户上传图片
     * 这个记录会在用户提交图片时被更新，而不是创建新记录
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param locationId 定位记录ID
     * @return 创建的打卡记录ID
     */
    private Long consumeCheckinCountForCompleted(Long userId, String sceneType, Long locationId) {
        // 创建一个状态为PENDING的打卡记录，标记为"待提交图片"
        // 这样可以消耗打卡次数，符合业务需求
        CheckinRecord record = new CheckinRecord();
        record.setUserId(userId);
        record.setSceneType(sceneType);
        record.setImageUrl(null); // 无图片，等待用户上传
        record.setImageHash(null);
        record.setStatus("PENDING"); // 待提交状态
        record.setRewardPoints(0);
        record.setVerifyReason("定位打卡完成，等待上传图片");
        record.setVerifySteps("[]"); // 空的验证步骤
        record.setSubmitTime(LocalDateTime.now());
        // 不设置verifyTime，因为还没有审核
        
        CheckinRecord savedRecord = checkinRecordRepository.save(record);
        
        // 关联定位记录到打卡记录
        CheckinLocation location = checkinLocationRepository.findById(locationId)
                .orElseThrow(() -> new BusinessException("定位记录不存在: " + locationId));
        location.setCheckinId(savedRecord.getId());
        checkinLocationRepository.save(location);
        
        log.info("创建待提交打卡记录，消耗打卡次数: userId={}, sceneType={}, locationId={}, recordId={}", 
                userId, sceneType, locationId, savedRecord.getId());
        
        return savedRecord.getId();
    }
    
    /**
     * 通过百度API获取地址（逆地理编码）
     * 
     * @param latitude 纬度
     * @param longitude 经度
     * @return 地址字符串
     */
    private String getAddressFromBaiduAPI(BigDecimal latitude, BigDecimal longitude) {
        try {
            String url = String.format(
                    "https://api.map.baidu.com/reverse_geocoding/v3/?ak=%s&output=json&coordtype=wgs84ll&location=%s,%s",
                    baiduMapApiKey,
                    latitude.toString(),
                    longitude.toString()
            );
            
            String response = restTemplate.getForObject(url, String.class);
            JsonNode jsonNode = objectMapper.readTree(response);
            
            if (jsonNode.has("status") && jsonNode.get("status").asInt() == 0) {
                JsonNode result = jsonNode.get("result");
                if (result != null && result.has("formatted_address")) {
                    return result.get("formatted_address").asText();
                }
            }
            
            log.warn("百度API逆地理编码失败: latitude={}, longitude={}, response={}", 
                    latitude, longitude, response);
            return "地址获取失败";
            
        } catch (Exception e) {
            log.error("调用百度API逆地理编码失败: latitude={}, longitude={}", latitude, longitude, e);
            return "地址获取失败";
        }
    }
    
    /**
     * 使用百度API计算两点之间的距离
     * 
     * @param lat1 起点纬度
     * @param lng1 起点经度
     * @param lat2 终点纬度
     * @param lng2 终点经度
     * @return 距离（米）
     */
    private BigDecimal calculateDistanceFromBaiduAPI(BigDecimal lat1, BigDecimal lng1, 
                                                     BigDecimal lat2, BigDecimal lng2) {
        try {
            String url = String.format(
                    "https://api.map.baidu.com/routematrix/v2/driving?ak=%s&output=json&origins=%s,%s&destinations=%s,%s",
                    baiduMapApiKey,
                    lat1.toString(),
                    lng1.toString(),
                    lat2.toString(),
                    lng2.toString()
            );
            
            String response = restTemplate.getForObject(url, String.class);
            JsonNode jsonNode = objectMapper.readTree(response);
            
            if (jsonNode.has("status") && jsonNode.get("status").asInt() == 0) {
                JsonNode result = jsonNode.get("result");
                if (result != null && result.isArray() && result.size() > 0) {
                    JsonNode element = result.get(0);
                    if (element.has("distance")) {
                        JsonNode distanceNode = element.get("distance");
                        if (distanceNode.has("value")) {
                            int distanceValue = distanceNode.get("value").asInt();
                            return new BigDecimal(distanceValue).setScale(2, RoundingMode.HALF_UP);
                        }
                    }
                }
            }
            
            // 如果API调用失败，使用Haversine公式计算直线距离（备用方案）
            log.warn("百度API距离计算失败，使用Haversine公式计算: response={}", response);
            return calculateHaversineDistance(lat1, lng1, lat2, lng2);
            
        } catch (Exception e) {
            log.error("调用百度API距离计算失败，使用Haversine公式计算", e);
            // 使用Haversine公式计算直线距离（备用方案）
            return calculateHaversineDistance(lat1, lng1, lat2, lng2);
        }
    }
    
    /**
     * 使用Haversine公式计算两点之间的直线距离（备用方案）
     * 
     * @param lat1 起点纬度
     * @param lng1 起点经度
     * @param lat2 终点纬度
     * @param lng2 终点经度
     * @return 距离（米）
     */
    private BigDecimal calculateHaversineDistance(BigDecimal lat1, BigDecimal lng1, 
                                                  BigDecimal lat2, BigDecimal lng2) {
        // 地球半径（米）
        final double EARTH_RADIUS = 6371000.0;
        
        double lat1Rad = Math.toRadians(lat1.doubleValue());
        double lat2Rad = Math.toRadians(lat2.doubleValue());
        double deltaLat = Math.toRadians(lat2.doubleValue() - lat1.doubleValue());
        double deltaLng = Math.toRadians(lng2.doubleValue() - lng1.doubleValue());
        
        double a = Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
                   Math.cos(lat1Rad) * Math.cos(lat2Rad) *
                   Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
        
        double c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        double distance = EARTH_RADIUS * c;
        
        return new BigDecimal(distance).setScale(2, RoundingMode.HALF_UP);
    }
    
    /**
     * 关联定位记录到打卡记录
     * 
     * @param locationId 定位记录ID
     * @param checkinId 打卡记录ID
     */
    @Transactional
    public void linkLocationToCheckin(Long locationId, Long checkinId) {
        CheckinLocation location = checkinLocationRepository.findById(locationId)
                .orElseThrow(() -> new BusinessException("定位记录不存在"));
        
        location.setCheckinId(checkinId);
        checkinLocationRepository.save(location);
        
        log.info("关联定位记录到打卡记录: locationId={}, checkinId={}", locationId, checkinId);
    }
}

