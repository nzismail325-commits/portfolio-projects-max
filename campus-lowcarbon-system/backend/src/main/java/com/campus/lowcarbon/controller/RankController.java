/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.RankDTO;
import com.campus.lowcarbon.service.RankService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 排行榜控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/rank")
@RequiredArgsConstructor
public class RankController {
    
    private final RankService rankService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取积分排行榜
     * 
     * @param request HTTP请求
     * @return 排行榜列表
     */
    @GetMapping("/points")
    public Result<List<RankDTO>> getPointsRank(HttpServletRequest request) {
        try {
            Long currentUserId = getCurrentUserId(request);
            boolean isAdmin = jwtAuthUtil.isAdmin(request);
            List<RankDTO> rankList = rankService.getPointsRank(currentUserId, isAdmin);
            return Result.success(rankList);
        } catch (Exception e) {
            return Result.error("获取积分排行榜失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取勋章排行榜
     * 
     * @param request HTTP请求
     * @return 排行榜列表
     */
    @GetMapping("/badges")
    public Result<List<RankDTO>> getBadgesRank(HttpServletRequest request) {
        try {
            Long currentUserId = getCurrentUserId(request);
            boolean isAdmin = jwtAuthUtil.isAdmin(request);
            List<RankDTO> rankList = rankService.getBadgesRank(currentUserId, isAdmin);
            return Result.success(rankList);
        } catch (Exception e) {
            return Result.error("获取勋章排行榜失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取称号排行榜
     * 
     * @param request HTTP请求
     * @return 排行榜列表
     */
    @GetMapping("/titles")
    public Result<List<RankDTO>> getTitlesRank(HttpServletRequest request) {
        try {
            Long currentUserId = getCurrentUserId(request);
            boolean isAdmin = jwtAuthUtil.isAdmin(request);
            List<RankDTO> rankList = rankService.getTitlesRank(currentUserId, isAdmin);
            return Result.success(rankList);
        } catch (Exception e) {
            return Result.error("获取称号排行榜失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取打卡排行榜
     * 
     * @param request HTTP请求
     * @return 排行榜列表
     */
    @GetMapping("/checkins")
    public Result<List<RankDTO>> getCheckinsRank(HttpServletRequest request) {
        try {
            Long currentUserId = getCurrentUserId(request);
            boolean isAdmin = jwtAuthUtil.isAdmin(request);
            List<RankDTO> rankList = rankService.getCheckinsRank(currentUserId, isAdmin);
            return Result.success(rankList);
        } catch (Exception e) {
            return Result.error("获取打卡排行榜失败：" + e.getMessage());
        }
    }
    
    /**
     * 设置排行榜展示
     * 
     * @param request HTTP请求
     * @param body 请求体 { type: "badge" | "title", itemId: 勋章ID或称号ID }
     * @return 操作结果
     */
    @PostMapping("/display")
    public Result<Void> setDisplay(HttpServletRequest request, @RequestBody Map<String, Object> body) {
        try {
            Long currentUserId = getCurrentUserId(request);
            if (currentUserId == null) {
                return Result.error(401, "未登录");
            }
            
            String type = (String) body.get("type");
            Long itemId = Long.valueOf(body.get("itemId").toString());
            
            boolean success = rankService.setDisplay(currentUserId, type, itemId);
            if (success) {
                return Result.success("设置成功");
            } else {
                return Result.error("设置失败：未找到对应的勋章或称号");
            }
        } catch (Exception e) {
            return Result.error("设置失败：" + e.getMessage());
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
        
        // 通过学号查找用户ID
        return rankService.getUserIdByStudentId(studentId);
    }
}

