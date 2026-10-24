/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.ReviewDTO;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.ReviewService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 异常审核控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/review")
@RequiredArgsConstructor
public class ReviewController {
    
    private final ReviewService reviewService;
    private final JwtAuthUtil jwtAuthUtil;
    private final UserRepository userRepository;
    
    /**
     * 获取审核列表（分页）
     * 
     * @param request HTTP请求
     * @param page 页码（从1开始，默认1）
     * @param pageSize 每页大小（默认10）
     * @param sceneType 场景类型筛选（可选）
     * @return 审核列表响应
     */
    @GetMapping("/list")
    public Result<ReviewDTO.ReviewListResponse> getReviewList(
            HttpServletRequest request,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "10") Integer pageSize,
            @RequestParam(required = false) String sceneType) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            ReviewDTO.ReviewListResponse response = reviewService.getReviewList(page, pageSize, sceneType);
            return Result.success(response);
        } catch (Exception e) {
            return Result.error("获取审核列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取审核统计数据
     * 
     * @param request HTTP请求
     * @return 统计数据
     */
    @GetMapping("/statistics")
    public Result<ReviewDTO.ReviewStatistics> getReviewStatistics(HttpServletRequest request) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            ReviewDTO.ReviewStatistics statistics = reviewService.getReviewStatistics();
            return Result.success(statistics);
        } catch (Exception e) {
            return Result.error("获取统计数据失败：" + e.getMessage());
        }
    }
    
    /**
     * 审核操作（通过或驳回）
     * 
     * @param request HTTP请求
     * @param reviewRequest 审核请求
     * @return 审核操作响应
     */
    @PostMapping("/action")
    public Result<ReviewDTO.ReviewActionResponse> reviewAction(
            HttpServletRequest request,
            @Valid @RequestBody ReviewDTO.ReviewActionRequest reviewRequest) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "无权限访问");
            }
            
            // 获取当前管理员ID（通过学号查询）
            String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
            if (studentId == null) {
                return Result.error(401, "未登录或登录已过期");
            }
            User reviewer = userRepository.findByStudentId(studentId)
                    .orElse(null);
            if (reviewer == null) {
                return Result.error(401, "用户不存在");
            }
            Long reviewerId = reviewer.getId();
            
            ReviewDTO.ReviewActionResponse response = reviewService.reviewAction(
                    reviewRequest.getReviewId(),
                    reviewRequest.getAction(),
                    reviewRequest.getComment(),
                    reviewerId,
                    reviewRequest.getExtractedValue());
            
            return Result.success(response);
        } catch (Exception e) {
            return Result.error("审核操作失败：" + e.getMessage());
        }
    }
}

