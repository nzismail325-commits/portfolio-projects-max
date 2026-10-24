/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.DashboardDTO;
import com.campus.lowcarbon.service.DashboardService;
import com.campus.lowcarbon.service.MallService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 首页控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
public class DashboardController {
    
    private final DashboardService dashboardService;
    private final MallService mallService;
    private final JwtAuthUtil jwtAuthUtil;
    
    /**
     * 获取首页数据（学生端）
     * 
     * @param request HTTP请求
     * @return 首页数据
     */
    @GetMapping("/data")
    public Result<DashboardDTO.DashboardData> getDashboardData(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            DashboardDTO.DashboardData data = dashboardService.getDashboardData(userId);
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取首页数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取管理员看板数据
     * 
     * @param request HTTP请求
     * @return 管理员看板数据
     */
    @GetMapping("/admin/data")
    public Result<DashboardDTO.AdminDashboardData> getAdminDashboardData(HttpServletRequest request) {
        try {
            // 验证管理员权限
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            // 这里可以添加管理员权限验证逻辑
            // 暂时允许所有登录用户访问，实际项目中应该验证role是否为admin
            
            DashboardDTO.AdminDashboardData data = dashboardService.getAdminDashboardData();
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取管理员看板数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取场景参与占比数据（用于饼图）
     * 注意：此接口返回基础统计数据，AI分析由前端直接调用Python服务
     * 
     * @param request HTTP请求
     * @param timeRange 时间范围：today-今日，week-本周，month-本月
     * @return 场景参与占比数据
     */
    @GetMapping("/admin/scene-participation")
    public Result<List<DashboardDTO.SceneParticipationData>> getSceneParticipation(
            HttpServletRequest request,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "today") String timeRange) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<DashboardDTO.SceneParticipationData> data = dashboardService.getSceneParticipation(timeRange);
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取场景参与占比数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取近七日活跃度数据（用于折线图）
     * 注意：此接口返回基础统计数据，AI分析由前端直接调用Python服务
     * 
     * @param request HTTP请求
     * @return 近七日活跃度数据
     */
    @GetMapping("/admin/activity")
    public Result<List<DashboardDTO.ActivityData>> getActivityData(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<DashboardDTO.ActivityData> data = dashboardService.getActivityData();
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取活跃度数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 计算场景参与占比分析（后端计算，AI断联时的备用方案）
     * 
     * @param request HTTP请求
     * @param timeRange 时间范围：today-今日，week-本周，month-本月
     * @return 分析结果
     */
    @GetMapping("/admin/scene-participation/analyze")
    public Result<DashboardDTO.SceneParticipationAnalysis> analyzeSceneParticipation(
            HttpServletRequest request,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "today") String timeRange) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<DashboardDTO.SceneParticipationData> data = dashboardService.getSceneParticipation(timeRange);
            DashboardDTO.SceneParticipationAnalysis analysis = dashboardService.calculateSceneParticipationAnalysis(data, timeRange);
            return Result.success(analysis);
        } catch (Exception e) {
            return Result.error("分析场景参与占比失败：" + e.getMessage());
        }
    }
    
    /**
     * 计算活跃度趋势分析（后端计算，AI断联时的备用方案）
     * 
     * @param request HTTP请求
     * @return 分析结果
     */
    @GetMapping("/admin/activity/analyze")
    public Result<DashboardDTO.ActivityTrendAnalysis> analyzeActivityTrend(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            List<DashboardDTO.ActivityData> data = dashboardService.getActivityData();
            DashboardDTO.ActivityTrendAnalysis analysis = dashboardService.calculateActivityTrendAnalysis(data);
            return Result.success(analysis);
        } catch (Exception e) {
            return Result.error("分析活跃度趋势失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取个人统计数据
     * 
     * @param request HTTP请求
     * @param timeRange 时间范围：week-近7天，month-近30天
     * @return 个人统计数据
     */
    @GetMapping("/personal/stats")
    public Result<DashboardDTO.PersonalStatsData> getPersonalStats(
            HttpServletRequest request,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "week") String timeRange) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            DashboardDTO.PersonalStatsData data = dashboardService.getPersonalStats(userId, timeRange);
            return Result.success(data);
        } catch (Exception e) {
            return Result.error("获取个人统计数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 计算个人数据详细分析（用于AI分析）
     * 
     * @param request HTTP请求
     * @param timeRange 时间范围：week-近7天，month-近30天
     * @return 详细分析结果
     */
    @GetMapping("/personal/analysis")
    public Result<DashboardDTO.PersonalDataCalculation> calculatePersonalAnalysis(
            HttpServletRequest request,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "week") String timeRange) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            DashboardDTO.PersonalDataCalculation calculation = dashboardService.calculatePersonalDataAnalysis(userId, timeRange);
            return Result.success(calculation);
        } catch (Exception e) {
            return Result.error("计算个人数据分析失败：" + e.getMessage());
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

