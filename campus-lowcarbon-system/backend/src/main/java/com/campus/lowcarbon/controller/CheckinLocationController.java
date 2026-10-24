/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.CheckinLocationService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

/**
 * 打卡位置控制器
 * 处理定位相关的请求
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/checkin/location")
@RequiredArgsConstructor
@Slf4j
public class CheckinLocationController {
    
    private final CheckinLocationService checkinLocationService;
    private final JwtAuthUtil jwtAuthUtil;
    private final UserRepository userRepository;
    
    /**
     * 开始打卡（记录起始位置）
     * 
     * @param request HTTP请求
     * @param body 请求体 { sceneType: "walk"|"ride"|"transit", latitude: 纬度, longitude: 经度 }
     * @return 定位记录ID
     */
    @PostMapping("/start")
    public Result<Map<String, Object>> startCheckinLocation(
            HttpServletRequest request,
            @RequestBody Map<String, Object> body) {
        
        try {
            // 1. 获取当前用户ID
            String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
            if (studentId == null) {
                return Result.error(401, "未登录");
            }
            
            Long userId = userRepository.findByStudentId(studentId)
                    .map(user -> user.getId())
                    .orElse(null);
            
            if (userId == null) {
                return Result.error(404, "用户不存在");
            }
            
            // 2. 获取参数
            String sceneType = (String) body.get("sceneType");
            Object latObj = body.get("latitude");
            Object lngObj = body.get("longitude");
            
            if (sceneType == null || sceneType.trim().isEmpty()) {
                return Result.error("场景类型不能为空");
            }
            
            if (latObj == null || lngObj == null) {
                return Result.error("经纬度不能为空");
            }
            
            // 验证场景类型
            String[] validSceneTypes = {"walk", "ride", "transit"};
            boolean isValidSceneType = false;
            for (String validType : validSceneTypes) {
                if (validType.equals(sceneType)) {
                    isValidSceneType = true;
                    break;
                }
            }
            if (!isValidSceneType) {
                return Result.error("无效的场景类型: " + sceneType + "，仅支持 walk、ride、transit");
            }
            
            // 转换经纬度为BigDecimal
            BigDecimal latitude;
            BigDecimal longitude;
            try {
                if (latObj instanceof Number) {
                    latitude = BigDecimal.valueOf(((Number) latObj).doubleValue());
                } else {
                    latitude = new BigDecimal(latObj.toString());
                }
                
                if (lngObj instanceof Number) {
                    longitude = BigDecimal.valueOf(((Number) lngObj).doubleValue());
                } else {
                    longitude = new BigDecimal(lngObj.toString());
                }
            } catch (Exception e) {
                return Result.error("经纬度格式错误");
            }
            
            // 3. 调用服务创建定位记录
            Long locationId = checkinLocationService.startCheckinLocation(userId, sceneType, latitude, longitude);
            
            Map<String, Object> result = new HashMap<>();
            result.put("id", locationId);
            result.put("message", "开始打卡成功");
            
            return Result.success("开始打卡成功", result);
            
        } catch (Exception e) {
            log.error("开始打卡失败", e);
            return Result.error("开始打卡失败: " + e.getMessage());
        }
    }
    
    /**
     * 结束打卡（记录结束位置并计算距离）
     * 
     * @param request HTTP请求
     * @param body 请求体 { locationId: 定位记录ID, latitude: 纬度, longitude: 经度 }
     * @return 距离和状态信息
     */
    @PostMapping("/end")
    public Result<Map<String, Object>> endCheckinLocation(
            HttpServletRequest request,
            @RequestBody Map<String, Object> body) {
        
        try {
            // 1. 获取当前用户ID
            String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
            if (studentId == null) {
                return Result.error(401, "未登录");
            }
            
            Long userId = userRepository.findByStudentId(studentId)
                    .map(user -> user.getId())
                    .orElse(null);
            
            if (userId == null) {
                return Result.error(404, "用户不存在");
            }
            
            // 2. 获取参数
            Object locationIdObj = body.get("locationId");
            Object latObj = body.get("latitude");
            Object lngObj = body.get("longitude");
            
            if (locationIdObj == null) {
                return Result.error("定位记录ID不能为空");
            }
            
            if (latObj == null || lngObj == null) {
                return Result.error("经纬度不能为空");
            }
            
            // 转换参数
            Long locationId;
            BigDecimal latitude;
            BigDecimal longitude;
            try {
                if (locationIdObj instanceof Number) {
                    locationId = ((Number) locationIdObj).longValue();
                } else {
                    locationId = Long.parseLong(locationIdObj.toString());
                }
                
                if (latObj instanceof Number) {
                    latitude = BigDecimal.valueOf(((Number) latObj).doubleValue());
                } else {
                    latitude = new BigDecimal(latObj.toString());
                }
                
                if (lngObj instanceof Number) {
                    longitude = BigDecimal.valueOf(((Number) lngObj).doubleValue());
                } else {
                    longitude = new BigDecimal(lngObj.toString());
                }
            } catch (Exception e) {
                return Result.error("参数格式错误");
            }
            
            // 3. 调用服务结束打卡并计算距离
            Map<String, Object> result = checkinLocationService.endCheckinLocation(locationId, latitude, longitude);
            
            return Result.success("结束打卡成功", result);
            
        } catch (Exception e) {
            log.error("结束打卡失败", e);
            return Result.error("结束打卡失败: " + e.getMessage());
        }
    }
}

