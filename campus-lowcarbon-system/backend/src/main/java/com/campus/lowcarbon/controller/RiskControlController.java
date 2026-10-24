/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.RiskControlDTO;
import com.campus.lowcarbon.service.RiskControlService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 用户风控控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/risk-control")
@RequiredArgsConstructor
public class RiskControlController {
    
    private final RiskControlService riskControlService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取用户风控列表
     * 
     * @param request HTTP请求
     * @param keyword 搜索关键词（学号或姓名，可选）
     * @param status 账号状态筛选（normal-正常，banned-已封禁，可选）
     * @return 用户风控列表
     */
    @GetMapping("/users")
    public Result<RiskControlDTO.UserRiskListResponse> getUserRiskList(
            HttpServletRequest request,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            RiskControlDTO.UserRiskListResponse response = riskControlService.getUserRiskList(keyword, status);
            return Result.success(response);
        } catch (Exception e) {
            return Result.error("获取用户风控列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 封禁用户
     * 
     * @param request HTTP请求
     * @param banRequest 封禁请求
     * @return 操作结果
     */
    @PostMapping("/ban")
    public Result<Void> banUser(
            HttpServletRequest request,
            @Valid @RequestBody RiskControlDTO.BanUserRequest banRequest) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            riskControlService.banUser(banRequest.getUserId(), banRequest.getReason());
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("封禁用户失败：" + e.getMessage());
        }
    }
    
    /**
     * 解封用户
     * 
     * @param request HTTP请求
     * @param unbanRequest 解封请求
     * @return 操作结果
     */
    @PostMapping("/unban")
    public Result<Void> unbanUser(
            HttpServletRequest request,
            @Valid @RequestBody RiskControlDTO.UnbanUserRequest unbanRequest) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            riskControlService.unbanUser(unbanRequest.getUserId());
            return Result.success(null);
        } catch (Exception e) {
            return Result.error("解封用户失败：" + e.getMessage());
        }
    }
    
    /**
     * 清除所有用户的Token（强制所有用户退出登录）
     * 
     * @param request HTTP请求
     * @return 操作结果（包含被清除token的用户数量）
     */
    @PostMapping("/clear-all-tokens")
    public Result<Integer> clearAllUserTokens(HttpServletRequest request) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            int count = riskControlService.clearAllUserTokens();
            return Result.success("已清除所有用户的登录状态", count);
        } catch (Exception e) {
            return Result.error("清除所有用户Token失败：" + e.getMessage());
        }
    }
}

