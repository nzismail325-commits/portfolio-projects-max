/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.UserInfoDTO;
import com.campus.lowcarbon.service.MallService;
import com.campus.lowcarbon.service.UserService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 用户信息控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/user")
@RequiredArgsConstructor
public class UserController {
    
    private final UserService userService;
    private final MallService mallService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取当前用户信息
     * 
     * @param request HTTP请求
     * @return 用户信息
     */
    @GetMapping("/info")
    public Result<UserInfoDTO.UserInfo> getUserInfo(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            UserInfoDTO.UserInfo info = userService.getUserInfo(userId);
            return Result.success(info);
        } catch (Exception e) {
            return Result.error("获取用户信息失败：" + e.getMessage());
        }
    }
    
    /**
     * 更新个人信息
     * 
     * @param request HTTP请求
     * @param updateRequest 更新请求
     * @return 操作结果
     */
    @PutMapping("/profile")
    public Result<Void> updateProfile(
            HttpServletRequest request,
            @Valid @RequestBody UserInfoDTO.UpdateProfileRequest updateRequest) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            userService.updateProfile(userId, updateRequest);
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("更新个人信息失败：" + e.getMessage());
        }
    }
    
    /**
     * 修改登录密码
     * 
     * @param request HTTP请求
     * @param changeRequest 修改密码请求
     * @return 操作结果
     */
    @PutMapping("/password")
    public Result<Void> changePassword(
            HttpServletRequest request,
            @Valid @RequestBody UserInfoDTO.ChangePasswordRequest changeRequest) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            userService.changePassword(userId, changeRequest);
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("修改密码失败：" + e.getMessage());
        }
    }
    
    /**
     * 设置支付密码
     * 
     * @param request HTTP请求
     * @param setRequest 设置支付密码请求
     * @return 操作结果
     */
    @PutMapping("/payment-password")
    public Result<Void> setPaymentPassword(
            HttpServletRequest request,
            @Valid @RequestBody UserInfoDTO.SetPaymentPasswordRequest setRequest) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            userService.setPaymentPassword(userId, setRequest);
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("设置支付密码失败：" + e.getMessage());
        }
    }
    
    /**
     * 关闭安全密码（删除支付密码）
     * 
     * @param request HTTP请求
     * @param body 请求体，包含支付密码
     * @return 操作结果
     */
    @DeleteMapping("/payment-password")
    public Result<Void> removePaymentPassword(
            HttpServletRequest request,
            @RequestBody java.util.Map<String, String> body) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            String paymentPassword = body != null ? body.get("paymentPassword") : null;
            userService.removePaymentPassword(userId, paymentPassword);
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("关闭安全密码失败：" + e.getMessage());
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

