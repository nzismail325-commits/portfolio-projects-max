/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.ProfileDTO;
import com.campus.lowcarbon.service.MallService;
import com.campus.lowcarbon.service.ProfileService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 我的荣誉页面控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/profile")
@RequiredArgsConstructor
public class ProfileController {
    
    private final ProfileService profileService;
    private final MallService mallService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取我的荣誉页面数据
     * 
     * @param request HTTP请求
     * @return 我的荣誉页面数据
     */
    @GetMapping("/data")
    public Result<ProfileDTO.ProfileData> getProfileData(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            ProfileDTO.ProfileData data = profileService.getProfileData(userId);
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取我的荣誉页面数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 从请求中获取当前用户ID
     * 
     * @param request HTTP请求
     * @return 用户ID（如果未登录则返回null）
     */
    private Long getCurrentUserId(HttpServletRequest request) {
        String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
        if (studentId == null) {
            return null;
        }
        
        return mallService.getUserRepository().findByStudentId(studentId)
                .map(user -> user.getId())
                .orElse(null);
    }
}

