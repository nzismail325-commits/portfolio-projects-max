/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.NotificationDTO;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.service.NotificationService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 通知消息控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/notification")
@RequiredArgsConstructor
@Slf4j
public class NotificationController {
    
    private final NotificationService notificationService;
    private final JwtAuthUtil jwtAuthUtil;
    private final UserRepository userRepository;
    
    /**
     * 获取未读消息数量
     * 
     * @param request HTTP请求
     * @return 未读数量
     */
    @GetMapping("/unread-count")
    public Result<NotificationDTO.UnreadCountResponse> getUnreadCount(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            Long unreadCount = notificationService.getUnreadCount(userId);
            
            NotificationDTO.UnreadCountResponse response = new NotificationDTO.UnreadCountResponse();
            response.setUnreadCount(unreadCount);
            
            return Result.success(response);
        } catch (Exception e) {
            log.error("获取未读消息数量失败", e);
            return Result.error("获取未读消息数量失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取消息列表
     * 
     * @param request HTTP请求
     * @param page 页码（从1开始，默认1）
     * @param pageSize 每页大小（默认20）
     * @param type 通知类型筛选（可选）
     * @param isRead 是否已读筛选（0-未读，1-已读，不传则全部）
     * @return 消息列表响应
     */
    @GetMapping("/list")
    public Result<NotificationDTO.ListResponse> getNotificationList(
            HttpServletRequest request,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "20") Integer pageSize,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) Integer isRead) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            NotificationDTO.ListResponse response = notificationService.getNotificationList(
                    userId, page, pageSize, type, isRead);
            
            return Result.success(response);
        } catch (Exception e) {
            log.error("获取消息列表失败", e);
            return Result.error("获取消息列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 标记消息为已读
     * 
     * @param request HTTP请求
     * @param notificationId 通知ID
     * @return 操作结果
     */
    @PutMapping("/{notificationId}/read")
    public Result<Void> markAsRead(HttpServletRequest request, @PathVariable Long notificationId) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            notificationService.markAsRead(notificationId, userId);
            return Result.success("标记已读成功");
        } catch (Exception e) {
            log.error("标记已读失败", e);
            return Result.error("标记已读失败：" + e.getMessage());
        }
    }
    
    /**
     * 标记所有消息为已读
     * 
     * @param request HTTP请求
     * @return 操作结果
     */
    @PutMapping("/read-all")
    public Result<Void> markAllAsRead(HttpServletRequest request) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            notificationService.markAllAsRead(userId);
            return Result.success("全部标记为已读成功");
        } catch (Exception e) {
            log.error("全部标记为已读失败", e);
            return Result.error("全部标记为已读失败：" + e.getMessage());
        }
    }
    
    /**
     * 删除消息
     * 
     * @param request HTTP请求
     * @param notificationId 通知ID
     * @return 操作结果
     */
    @DeleteMapping("/{notificationId}")
    public Result<Void> deleteNotification(HttpServletRequest request, @PathVariable Long notificationId) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.error(401, "未登录");
            }
            
            notificationService.deleteNotification(notificationId, userId);
            return Result.success("删除成功");
        } catch (Exception e) {
            log.error("删除消息失败", e);
            return Result.error("删除消息失败：" + e.getMessage());
        }
    }
    
    /**
     * 发送邮件（管理员给学生）
     * 
     * @param request HTTP请求
     * @param sendMailRequest 发送邮件请求
     * @return 发送结果
     */
    @PostMapping("/send")
    public Result<NotificationDTO.SendMailResponse> sendMail(
            HttpServletRequest request,
            @Valid @RequestBody NotificationDTO.SendMailRequest sendMailRequest) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "只有管理员可以发送邮件");
            }
            
            Long senderId = getCurrentUserId(request);
            if (senderId == null) {
                return Result.error(401, "未登录");
            }
            
            NotificationDTO.SendMailResponse response = notificationService.sendMail(senderId, sendMailRequest);
            return Result.success(response);
        } catch (Exception e) {
            log.error("发送邮件失败", e);
            return Result.error("发送邮件失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取学生列表（用于选择收件人）
     * 
     * @param request HTTP请求
     * @param keyword 搜索关键词（姓名或学号）
     * @param grade 年级筛选（如"2021"）
     * @param className 班级筛选
     * @return 学生列表
     */
    @GetMapping("/students")
    public Result<java.util.List<NotificationDTO.StudentInfo>> getStudentList(
            HttpServletRequest request,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String grade,
            @RequestParam(required = false) String className) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "只有管理员可以查看学生列表");
            }
            
            java.util.List<NotificationDTO.StudentInfo> students = notificationService.getStudentList(
                    keyword, grade, className);
            
            return Result.success(students);
        } catch (Exception e) {
            log.error("获取学生列表失败", e);
            return Result.error("获取学生列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取年级列表
     * 
     * @param request HTTP请求
     * @return 年级列表
     */
    @GetMapping("/grades")
    public Result<NotificationDTO.GradeListResponse> getGradeList(HttpServletRequest request) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "只有管理员可以查看年级列表");
            }
            
            java.util.List<NotificationDTO.GradeInfo> grades = notificationService.getGradeList();
            
            NotificationDTO.GradeListResponse response = new NotificationDTO.GradeListResponse();
            response.setGrades(grades);
            
            return Result.success(response);
        } catch (Exception e) {
            log.error("获取年级列表失败", e);
            return Result.error("获取年级列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取班级列表（包含年级信息）
     * 
     * @param request HTTP请求
     * @param keyword 搜索关键词（可选，用于搜索班级名称）
     * @return 班级列表
     */
    @GetMapping("/classes")
    public Result<NotificationDTO.ClassListResponse> getClassList(
            HttpServletRequest request,
            @RequestParam(required = false) String keyword) {
        try {
            // 检查管理员权限
            if (!jwtAuthUtil.isAdmin(request)) {
                return Result.error(403, "只有管理员可以查看班级列表");
            }
            
            java.util.List<NotificationDTO.ClassInfo> classes = notificationService.getClassList(keyword);
            
            NotificationDTO.ClassListResponse response = new NotificationDTO.ClassListResponse();
            response.setClasses(classes);
            
            return Result.success(response);
        } catch (Exception e) {
            log.error("获取班级列表失败", e);
            return Result.error("获取班级列表失败：" + e.getMessage());
        }
    }
    
    /**
     * 获取当前用户ID
     */
    private Long getCurrentUserId(HttpServletRequest request) {
        String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
        if (studentId == null) {
            return null;
        }
        
        return userRepository.findByStudentId(studentId)
                .map(User::getId)
                .orElse(null);
    }
}

