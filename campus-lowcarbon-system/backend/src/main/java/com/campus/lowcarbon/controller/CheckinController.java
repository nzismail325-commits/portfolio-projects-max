/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.CheckinService;
import com.campus.lowcarbon.service.CheckinLocationService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.HashMap;
import java.util.Map;

/**
 * 打卡控制器
 * 处理用户打卡相关请求
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/checkin")
@RequiredArgsConstructor
@Slf4j
public class CheckinController {
    
    private final CheckinService checkinService;
    private final CheckinLocationService checkinLocationService;
    private final JwtAuthUtil jwtAuthUtil;
    private final UserRepository userRepository;
    
    /**
     * 检查每日打卡次数限制（在用户上传图片或点击开始打卡时调用）
     * 
     * @param request HTTP请求
     * @param sceneType 场景类型
     * @return 检查结果
     */
    @GetMapping("/check-limit")
    public Result<Map<String, Object>> checkDailyLimit(
            HttpServletRequest request,
            @RequestParam("sceneType") String sceneType) {
        
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
            
            // 2. 验证场景类型
            String[] validSceneTypes = {"walk", "ride", "plate", "transit"};
            boolean isValidSceneType = false;
            for (String validType : validSceneTypes) {
                if (validType.equals(sceneType)) {
                    isValidSceneType = true;
                    break;
                }
            }
            if (!isValidSceneType) {
                return Result.error("无效的场景类型: " + sceneType);
            }
            
            // 3. 检查每日打卡次数限制
            checkinService.checkDailyLimit(userId, sceneType);
            
            // 4. 返回成功结果
            Map<String, Object> result = new HashMap<>();
            result.put("canCheckin", true);
            result.put("message", "可以打卡");
            
            return Result.success("检查通过", result);
            
        } catch (RuntimeException e) {
            // 次数限制异常
            Map<String, Object> resultData = new HashMap<>();
            resultData.put("canCheckin", false);
            resultData.put("message", e.getMessage());
            Result<Map<String, Object>> result = new Result<>();
            result.setCode(403);
            result.setMessage(e.getMessage());
            result.setData(resultData);
            return result;
        } catch (Exception e) {
            log.error("检查每日打卡次数限制失败", e);
            return Result.error("检查失败: " + e.getMessage());
        }
    }
    
    /**
     * 提交打卡记录
     * 
     * @param request HTTP请求
     * @param imageFile 图片文件
     * @param sceneType 场景类型
     * @param status 验证状态（APPROVED/REJECTED/SUSPICIOUS）
     * @param verifyReason 验证原因
     * @param verifySteps 验证步骤详情（JSON字符串）
     * @param imageHash 图片MD5哈希值
     * @param rewardPoints 奖励积分（仅当status=APPROVED时有效）
     * @param locationId 定位记录ID（可选，如果使用了定位功能）
     * @return 打卡记录ID
     */
    @PostMapping("/submit")
    public Result<Map<String, Object>> submitCheckin(
            HttpServletRequest request,
            @RequestParam("image") MultipartFile imageFile,
            @RequestParam("sceneType") String sceneType,
            @RequestParam("status") String status,
            @RequestParam(value = "verifyReason", required = false) String verifyReason,
            @RequestParam(value = "verifySteps", required = false) String verifySteps,
            @RequestParam(value = "imageHash", required = false) String imageHash,
            @RequestParam(value = "rewardPoints", required = false) Integer rewardPoints,
            @RequestParam(value = "locationId", required = false) Long locationId) {
        
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
            
            // 2. 验证参数
            if (imageFile == null || imageFile.isEmpty()) {
                return Result.error("图片文件不能为空");
            }
            
            if (sceneType == null || sceneType.trim().isEmpty()) {
                return Result.error("场景类型不能为空");
            }
            
            if (status == null || status.trim().isEmpty()) {
                return Result.error("验证状态不能为空");
            }
            
            // 验证场景类型
            String[] validSceneTypes = {"walk", "ride", "plate", "transit"};
            boolean isValidSceneType = false;
            for (String validType : validSceneTypes) {
                if (validType.equals(sceneType)) {
                    isValidSceneType = true;
                    break;
                }
            }
            if (!isValidSceneType) {
                return Result.error("无效的场景类型: " + sceneType);
            }
            
            // 验证状态
            String[] validStatuses = {"APPROVED", "REJECTED", "SUSPICIOUS"};
            boolean isValidStatus = false;
            for (String validStatus : validStatuses) {
                if (validStatus.equals(status)) {
                    isValidStatus = true;
                    break;
                }
            }
            if (!isValidStatus) {
                return Result.error("无效的验证状态: " + status);
            }
            
            // 3. 保存打卡记录
            Long recordId = checkinService.saveCheckinRecord(
                    userId,
                    sceneType,
                    imageFile,
                    status,
                    verifyReason,
                    verifySteps,
                    imageHash,
                    rewardPoints,
                    locationId
            );
            
            // 4. 如果提供了定位记录ID，关联定位记录到打卡记录
            if (locationId != null) {
                try {
                    checkinLocationService.linkLocationToCheckin(locationId, recordId);
                } catch (Exception e) {
                    log.warn("关联定位记录失败: locationId={}, recordId={}, error={}", 
                            locationId, recordId, e.getMessage());
                    // 不影响打卡记录的保存，只记录警告日志
                }
            }
            
            // 5. 查询保存后的记录，获取实际积分（用于动态积分计算后的实际值）
            Integer actualRewardPoints = checkinService.getCheckinRecordRewardPoints(recordId);
            
            Map<String, Object> result = new HashMap<>();
            result.put("recordId", recordId);
            result.put("status", status);
            result.put("rewardPoints", actualRewardPoints != null ? actualRewardPoints : 0); // 返回实际积分
            result.put("message", "APPROVED".equals(status) ? "打卡成功" : 
                       "SUSPICIOUS".equals(status) ? "已提交人工审核" : "打卡未通过");
            
            return Result.success("打卡记录保存成功", result);
            
        } catch (Exception e) {
            log.error("提交打卡记录失败", e);
            return Result.error("提交打卡记录失败: " + e.getMessage());
        }
    }
}

