/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.MallDTO;
import com.campus.lowcarbon.service.MallService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 商城控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/mall")
@RequiredArgsConstructor
public class MallController {
    
    private final MallService mallService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取用户资产信息
     * 
     * @param request HTTP请求
     * @return 用户资产信息
     */
    @GetMapping("/assets")
    public Result<MallDTO.UserAssets> getUserAssets(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            MallDTO.UserAssets assets = mallService.getUserAssets(userId);
            return Result.success(assets);
        } catch (Exception e) {
            return Result.error("获取用户资产信息失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取用户统计数据
     * 
     * @param request HTTP请求
     * @return 用户统计数据
     */
    @GetMapping("/stats")
    public Result<MallDTO.UserStats> getUserStats(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            MallDTO.UserStats stats = mallService.getUserStats(userId);
            return Result.success(stats);
        } catch (Exception e) {
            return Result.error("获取用户统计数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取所有称号列表
     * 
     * @param request HTTP请求
     * @return 称号列表
     */
    @GetMapping("/titles")
    public Result<List<MallDTO.TitleInfo>> getAllTitles(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<MallDTO.TitleInfo> titles = mallService.getAllTitles(userId);
            return Result.success(titles);
        } catch (Exception e) {
            return Result.error("获取称号列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取所有勋章列表
     * 
     * @param request HTTP请求
     * @return 勋章列表
     */
    @GetMapping("/badges")
    public Result<List<MallDTO.BadgeInfo>> getAllBadges(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<MallDTO.BadgeInfo> badges = mallService.getAllBadges(userId);
            return Result.success(badges);
        } catch (Exception e) {
            return Result.error("获取勋章列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 解锁/升级称号
     * 
     * @param request HTTP请求
     * @param titleId 称号ID
     * @param body 请求体，包含支付密码（可选）
     * @return 操作后的称号信息
     */
    @PostMapping("/titles/{titleId}/upgrade")
    public Result<MallDTO.TitleInfo> upgradeTitle(
            HttpServletRequest request, 
            @PathVariable Long titleId,
            @RequestBody(required = false) java.util.Map<String, Object> body) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            // 从请求体中获取支付密码（如果提供）
            String paymentPassword = null;
            if (body != null && body.containsKey("paymentPassword")) {
                paymentPassword = (String) body.get("paymentPassword");
            }
            
            MallDTO.TitleInfo titleInfo = mallService.upgradeTitle(userId, titleId, paymentPassword);
            return Result.success("操作成功", titleInfo);
        } catch (Exception e) {
            return Result.error("操作失败：" + e.getMessage());
        }
    }
    
    /**
     * 佩戴/卸下称号
     * 
     * @param request HTTP请求
     * @param titleId 称号ID
     * @return 操作后的称号信息
     */
    @PostMapping("/titles/{titleId}/equip")
    public Result<MallDTO.TitleInfo> toggleEquipTitle(HttpServletRequest request, @PathVariable Long titleId) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            MallDTO.TitleInfo titleInfo = mallService.toggleEquipTitle(userId, titleId);
            return Result.success("操作成功", titleInfo);
        } catch (Exception e) {
            return Result.error("操作失败：" + e.getMessage());
        }
    }
    
    /**
     * 解锁勋章
     * 
     * @param request HTTP请求
     * @param badgeId 勋章ID
     * @return 操作后的勋章信息
     */
    @PostMapping("/badges/{badgeId}/unlock")
    public Result<MallDTO.BadgeInfo> unlockBadge(HttpServletRequest request, @PathVariable Long badgeId) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            MallDTO.BadgeInfo badgeInfo = mallService.unlockBadge(userId, badgeId);
            return Result.success("解锁成功", badgeInfo);
        } catch (Exception e) {
            return Result.error("解锁失败：" + e.getMessage());
        }
    }
    
    /**
     * 佩戴/卸下勋章
     * 
     * @param request HTTP请求
     * @param badgeId 勋章ID
     * @return 操作后的勋章信息
     */
    @PostMapping("/badges/{badgeId}/equip")
    public Result<MallDTO.BadgeInfo> toggleEquipBadge(HttpServletRequest request, @PathVariable Long badgeId) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            MallDTO.BadgeInfo badgeInfo = mallService.toggleEquipBadge(userId, badgeId);
            return Result.success("操作成功", badgeInfo);
        } catch (Exception e) {
            return Result.error("操作失败：" + e.getMessage());
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

