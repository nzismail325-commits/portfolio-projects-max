/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.NotificationDTO;
import com.campus.lowcarbon.entity.Notification;
import com.campus.lowcarbon.entity.StudentInfo;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.NotificationRepository;
import com.campus.lowcarbon.repository.StudentInfoRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.util.JsonUtil;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 通知消息服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class NotificationService {
    
    private final NotificationRepository notificationRepository;
    private final UserRepository userRepository;
    private final StudentInfoRepository studentInfoRepository;
    private final ObjectMapper objectMapper = new ObjectMapper();
    
    /**
     * 获取未读消息数量
     * 
     * @param receiverId 接收者ID
     * @return 未读数量
     */
    @Transactional(readOnly = true)
    public Long getUnreadCount(Long receiverId) {
        return notificationRepository.countByReceiverIdAndIsRead(receiverId, 0);
    }
    
    /**
     * 获取消息列表（分页）
     * 
     * @param receiverId 接收者ID
     * @param page 页码（从1开始）
     * @param pageSize 每页大小
     * @param type 通知类型筛选（可选）
     * @param isRead 是否已读筛选（0-未读，1-已读，null-全部）
     * @return 消息列表响应
     */
    @Transactional(readOnly = true)
    public NotificationDTO.ListResponse getNotificationList(
            Long receiverId, Integer page, Integer pageSize, String type, Integer isRead) {
        // 页码从1开始，转换为从0开始
        int pageIndex = (page == null || page < 1) ? 0 : page - 1;
        int size = (pageSize == null || pageSize < 1) ? 20 : pageSize;
        
        Pageable pageable = PageRequest.of(pageIndex, size);
        
        // 查询通知列表
        Page<Notification> notificationPage;
        if (type != null && !type.trim().isEmpty() && isRead != null) {
            notificationPage = notificationRepository.findByReceiverIdAndTypeAndIsReadOrderByCreatedAtDesc(
                    receiverId, type.trim(), isRead, pageable);
        } else if (type != null && !type.trim().isEmpty()) {
            notificationPage = notificationRepository.findByReceiverIdAndTypeOrderByCreatedAtDesc(
                    receiverId, type.trim(), pageable);
        } else if (isRead != null) {
            notificationPage = notificationRepository.findByReceiverIdAndIsReadOrderByCreatedAtDesc(
                    receiverId, isRead, pageable);
        } else {
            notificationPage = notificationRepository.findByReceiverIdOrderByCreatedAtDesc(receiverId, pageable);
        }
        
        // 转换为DTO
        List<NotificationDTO.NotificationInfo> records = notificationPage.getContent().stream()
                .map(this::convertToNotificationInfo)
                .collect(Collectors.toList());
        
        // 获取未读数量
        Long unreadCount = notificationRepository.countByReceiverIdAndIsRead(receiverId, 0);
        
        // 构建响应
        NotificationDTO.ListResponse response = new NotificationDTO.ListResponse();
        response.setRecords(records);
        response.setTotal(notificationPage.getTotalElements());
        response.setPage(pageIndex + 1);
        response.setPageSize(size);
        response.setUnreadCount(unreadCount);
        
        return response;
    }
    
    /**
     * 标记消息为已读
     * 
     * @param notificationId 通知ID
     * @param receiverId 接收者ID（用于验证权限）
     */
    @Transactional
    public void markAsRead(Long notificationId, Long receiverId) {
        Notification notification = notificationRepository.findById(notificationId)
                .orElseThrow(() -> new BusinessException("通知不存在"));
        
        // 验证权限：只能标记自己的通知
        if (!notification.getReceiverId().equals(receiverId)) {
            throw new BusinessException("无权限操作此通知");
        }
        
        if (notification.getIsRead() == 0) {
            notification.setIsRead(1);
            notification.setReadAt(LocalDateTime.now());
            notificationRepository.save(notification);
        }
    }
    
    /**
     * 标记所有消息为已读
     * 
     * @param receiverId 接收者ID
     */
    @Transactional
    public void markAllAsRead(Long receiverId) {
        List<Notification> unreadNotifications = notificationRepository.findByReceiverId(receiverId)
                .stream()
                .filter(n -> n.getIsRead() == 0)
                .collect(Collectors.toList());
        
        LocalDateTime now = LocalDateTime.now();
        for (Notification notification : unreadNotifications) {
            notification.setIsRead(1);
            notification.setReadAt(now);
        }
        
        notificationRepository.saveAll(unreadNotifications);
    }
    
    /**
     * 删除消息
     * 
     * @param notificationId 通知ID
     * @param receiverId 接收者ID（用于验证权限）
     */
    @Transactional
    public void deleteNotification(Long notificationId, Long receiverId) {
        Notification notification = notificationRepository.findById(notificationId)
                .orElseThrow(() -> new BusinessException("通知不存在"));
        
        // 验证权限：只能删除自己的通知
        if (!notification.getReceiverId().equals(receiverId)) {
            throw new BusinessException("无权限删除此通知");
        }
        
        notificationRepository.delete(notification);
    }
    
    /**
     * 发送邮件（管理员给学生）
     * 
     * @param senderId 发送者ID（管理员）
     * @param request 发送邮件请求
     * @return 发送结果
     */
    @Transactional
    public NotificationDTO.SendMailResponse sendMail(Long senderId, NotificationDTO.SendMailRequest request) {
        // 验证发送者必须是管理员
        User sender = userRepository.findById(senderId)
                .orElseThrow(() -> new BusinessException("发送者不存在"));
        if (!"admin".equals(sender.getRole())) {
            throw new BusinessException("只有管理员可以发送邮件");
        }
        
        // 获取收件人ID列表
        List<Long> receiverIds = getReceiverIds(request);
        
        if (receiverIds.isEmpty()) {
            throw new BusinessException("未找到符合条件的收件人");
        }
        
        // 批量创建通知
        List<Notification> notifications = new ArrayList<>();
        LocalDateTime now = LocalDateTime.now();
        
        for (Long receiverId : receiverIds) {
            Notification notification = new Notification();
            notification.setSenderId(senderId);
            notification.setReceiverId(receiverId);
            notification.setType("MAIL");
            notification.setTitle(request.getTitle());
            notification.setContent(request.getContent());
            notification.setIsRead(0);
            notification.setCreatedAt(now);
            notifications.add(notification);
        }
        
        notificationRepository.saveAll(notifications);
        
        NotificationDTO.SendMailResponse response = new NotificationDTO.SendMailResponse();
        response.setSuccessCount(receiverIds.size());
        response.setFailCount(0);
        response.setMessage("成功发送给 " + receiverIds.size() + " 位学生");
        
        log.info("管理员 {} 发送邮件给 {} 位学生，主题：{}", sender.getUsername(), receiverIds.size(), request.getTitle());
        
        return response;
    }
    
    /**
     * 获取收件人ID列表（根据发送类型）
     */
    private List<Long> getReceiverIds(NotificationDTO.SendMailRequest request) {
        List<Long> receiverIds = new ArrayList<>();
        
        switch (request.getSendType()) {
            case "SINGLE":
            case "BATCH":
                // 单个或批量发送：直接使用receiverIds
                if (request.getReceiverIds() != null && !request.getReceiverIds().isEmpty()) {
                    receiverIds.addAll(request.getReceiverIds());
                }
                break;
                
            case "GRADE":
                // 按年级发送：查找学号以"20XX"开头的学生
                // 注意：前端已经发送完整的4位年级（如"2021"），这里直接使用
                if (request.getFilterValue() != null && !request.getFilterValue().trim().isEmpty()) {
                    String gradePrefix = request.getFilterValue().trim();
                    List<User> students = userRepository.findByRoleAndStatus("student", 1);
                    List<Long> gradeStudentIds = students.stream()
                            .filter(u -> u.getStudentId() != null && u.getStudentId().startsWith(gradePrefix))
                            .map(User::getId)
                            .collect(Collectors.toList());
                    receiverIds.addAll(gradeStudentIds);
                }
                break;
                
            case "CLASS":
                // 按班级发送：查找指定班级的学生
                if (request.getFilterValue() != null && !request.getFilterValue().trim().isEmpty()) {
                    String className = request.getFilterValue().trim();
                    List<StudentInfo> studentInfos = studentInfoRepository.findAll().stream()
                            .filter(s -> className.equals(s.getClassName()) && s.getStatus() == 1)
                            .collect(Collectors.toList());
                    
                    for (StudentInfo studentInfo : studentInfos) {
                        userRepository.findByStudentId(studentInfo.getStudentId())
                                .filter(u -> "student".equals(u.getRole()) && u.getStatus() == 1)
                                .ifPresent(u -> receiverIds.add(u.getId()));
                    }
                }
                break;
        }
        
        return receiverIds;
    }
    
    /**
     * 获取学生列表（用于选择收件人）
     * 
     * @param keyword 搜索关键词（姓名或学号）
     * @param grade 年级筛选（如"2021"）
     * @param className 班级筛选
     * @return 学生列表
     */
    @Transactional(readOnly = true)
    public List<NotificationDTO.StudentInfo> getStudentList(String keyword, String grade, String className) {
        List<User> students = userRepository.findByRoleAndStatus("student", 1);
        
        // 应用筛选条件
        if (keyword != null && !keyword.trim().isEmpty()) {
            String keywordLower = keyword.trim().toLowerCase();
            students = students.stream()
                    .filter(u -> (u.getUsername() != null && u.getUsername().toLowerCase().contains(keywordLower))
                            || (u.getStudentId() != null && u.getStudentId().toLowerCase().contains(keywordLower)))
                    .collect(Collectors.toList());
        }
        
        if (grade != null && !grade.trim().isEmpty()) {
            String gradePrefix = "20" + grade.trim();
            students = students.stream()
                    .filter(u -> u.getStudentId() != null && u.getStudentId().startsWith(gradePrefix))
                    .collect(Collectors.toList());
        }
        
        if (className != null && !className.trim().isEmpty()) {
            Set<String> studentIdsInClass = studentInfoRepository.findAll().stream()
                    .filter(s -> className.trim().equals(s.getClassName()) && s.getStatus() == 1)
                    .map(StudentInfo::getStudentId)
                    .collect(Collectors.toSet());
            
            students = students.stream()
                    .filter(u -> studentIdsInClass.contains(u.getStudentId()))
                    .collect(Collectors.toList());
        }
        
        // 转换为DTO
        return students.stream()
                .map(user -> {
                    NotificationDTO.StudentInfo info = new NotificationDTO.StudentInfo();
                    info.setId(user.getId());
                    info.setName(user.getUsername());
                    info.setStudentId(user.getStudentId());
                    
                    // 获取班级和学院信息
                    studentInfoRepository.findByStudentId(user.getStudentId())
                            .ifPresent(studentInfo -> {
                                info.setClassName(studentInfo.getClassName());
                                info.setCollege(studentInfo.getCollege());
                            });
                    
                    return info;
                })
                .collect(Collectors.toList());
    }
    
    /**
     * 创建通知（内部方法，供其他服务调用）
     * 
     * @param senderId 发送者ID（null表示系统自动发送）
     * @param receiverId 接收者ID
     * @param type 通知类型
     * @param title 通知标题
     * @param content 通知内容
     * @param relatedType 关联类型
     * @param relatedId 关联ID
     * @param extraData 额外数据
     */
    @Transactional
    public void createNotification(Long senderId, Long receiverId, String type, String title, String content,
                                   String relatedType, Long relatedId, Map<String, Object> extraData) {
        try {
            Notification notification = new Notification();
            notification.setSenderId(senderId);
            notification.setReceiverId(receiverId);
            notification.setType(type);
            notification.setTitle(title);
            notification.setContent(content);
            notification.setRelatedType(relatedType);
            notification.setRelatedId(relatedId);
            notification.setIsRead(0);
            
            // 将extraData转换为JSON字符串
            if (extraData != null && !extraData.isEmpty()) {
                try {
                    notification.setExtraData(objectMapper.writeValueAsString(extraData));
                } catch (Exception e) {
                    log.error("转换extraData为JSON失败", e);
                }
            }
            
            notificationRepository.save(notification);
            log.info("创建通知成功: receiverId={}, type={}, title={}", receiverId, type, title);
        } catch (Exception e) {
            log.error("创建通知失败: receiverId={}, type={}, title={}", receiverId, type, title, e);
            // 不抛出异常，避免影响主业务流程
        }
    }
    
    /**
     * 创建人工复核通知（给所有管理员）
     * 
     * @param checkinId 打卡记录ID
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param userName 用户姓名
     */
    @Transactional
    public void createReviewNotification(Long checkinId, Long userId, String sceneType, String userName) {
        // 获取所有管理员ID
        List<User> admins = userRepository.findByRoleAndStatus("admin", 1);
        
        if (admins.isEmpty()) {
            log.warn("没有找到管理员，无法发送复核通知");
            return;
        }
        
        // 获取场景名称
        String sceneName = getSceneName(sceneType);
        
        // 为每个管理员创建通知
        for (User admin : admins) {
            Map<String, Object> extraData = new HashMap<>();
            extraData.put("checkinId", checkinId);
            extraData.put("userId", userId);
            extraData.put("sceneType", sceneType);
            extraData.put("userName", userName);
            
            createNotification(
                    null, // 系统自动发送
                    admin.getId(),
                    "REVIEW",
                    "有新的待审核记录",
                    String.format("用户%s的%s打卡申请已转入人工复核池，请及时审核。", userName, sceneName),
                    "CHECKIN",
                    checkinId,
                    extraData
            );
        }
        
        log.info("已为{}位管理员创建复核通知，打卡记录ID：{}", admins.size(), checkinId);
    }
    
    /**
     * 创建驳回通知（给用户）
     * 
     * @param userId 用户ID
     * @param checkinId 打卡记录ID
     * @param sceneType 场景类型
     * @param reason 驳回理由
     */
    @Transactional
    public void createRejectNotification(Long userId, Long checkinId, String sceneType, String reason) {
        String sceneName = getSceneName(sceneType);
        
        Map<String, Object> extraData = new HashMap<>();
        extraData.put("checkinId", checkinId);
        extraData.put("sceneType", sceneType);
        
        createNotification(
                null, // 系统自动发送
                userId,
                "REJECT",
                "打卡申请被驳回",
                String.format("您的%s打卡申请已被管理员驳回。驳回理由：%s", sceneName, reason),
                "CHECKIN",
                checkinId,
                extraData
        );
    }
    
    /**
     * 创建审核通过通知（给用户）
     * 
     * @param userId 用户ID
     * @param checkinId 打卡记录ID
     * @param sceneType 场景类型
     * @param rewardPoints 奖励积分
     */
    @Transactional
    public void createApproveNotification(Long userId, Long checkinId, String sceneType, Integer rewardPoints) {
        String sceneName = getSceneName(sceneType);
        
        Map<String, Object> extraData = new HashMap<>();
        extraData.put("checkinId", checkinId);
        extraData.put("sceneType", sceneType);
        extraData.put("rewardPoints", rewardPoints);
        
        createNotification(
                null, // 系统自动发送
                userId,
                "APPROVE",
                "打卡申请已通过",
                String.format("您的%s打卡申请已通过管理员审核，获得%d积分奖励。", sceneName, rewardPoints),
                "CHECKIN",
                checkinId,
                extraData
        );
    }
    
    /**
     * 创建转入人工复核通知（给用户）
     * 
     * @param userId 用户ID
     * @param checkinId 打卡记录ID
     * @param sceneType 场景类型
     */
    @Transactional
    public void createReviewPendingNotification(Long userId, Long checkinId, String sceneType) {
        String sceneName = getSceneName(sceneType);
        
        Map<String, Object> extraData = new HashMap<>();
        extraData.put("checkinId", checkinId);
        extraData.put("sceneType", sceneType);
        
        createNotification(
                null, // 系统自动发送
                userId,
                "SYSTEM",
                "打卡申请转入人工复核",
                String.format("您的%s打卡申请需要人工复核，请耐心等待管理员审核。", sceneName),
                "CHECKIN",
                checkinId,
                extraData
        );
    }

    /**
     * 将Notification实体转换为NotificationInfo DTO
     */
    private NotificationDTO.NotificationInfo convertToNotificationInfo(Notification notification) {
        NotificationDTO.NotificationInfo info = new NotificationDTO.NotificationInfo();
        info.setId(notification.getId());
        info.setType(notification.getType());
        info.setTitle(notification.getTitle());
        info.setContent(notification.getContent());
        info.setIsRead(notification.getIsRead() == 1);
        info.setCreatedAt(notification.getCreatedAt());
        
        // 获取发送者姓名
        if (notification.getSenderId() != null) {
            userRepository.findById(notification.getSenderId())
                    .ifPresent(sender -> info.setSenderName(sender.getUsername()));
        }
        
        // 解析extraData
        if (notification.getExtraData() != null && !notification.getExtraData().trim().isEmpty()) {
            try {
                Map<String, Object> extraData = objectMapper.readValue(
                        notification.getExtraData(),
                        new TypeReference<Map<String, Object>>() {}
                );
                info.setExtraData(extraData);
            } catch (Exception e) {
                log.error("解析extraData失败", e);
            }
        }
        
        return info;
    }
    
    /**
     * 获取场景名称
     */
    private String getSceneName(String sceneType) {
        switch (sceneType) {
            case "walk":
                return "低碳健步走";
            case "ride":
                return "绿色骑行";
            case "plate":
                return "光盘行动";
            case "transit":
                return "公共交通";
            default:
                return sceneType;
        }
    }
    
    /**
     * 获取年级列表（从学号中提取）
     * 
     * @return 年级列表
     */
    @Transactional(readOnly = true)
    public List<NotificationDTO.GradeInfo> getGradeList() {
        // 获取所有学生用户
        List<User> students = userRepository.findByRoleAndStatus("student", 1);
        
        // 从学号中提取年级（学号格式：20XX...）
        Set<String> gradeSet = new TreeSet<>();
        for (User student : students) {
            if (student.getStudentId() != null && student.getStudentId().length() >= 4) {
                String grade = student.getStudentId().substring(0, 4); // 取前4位（如"2021"）
                if (grade.startsWith("20")) {
                    gradeSet.add(grade);
                }
            }
        }
        
        // 转换为DTO
        return gradeSet.stream()
                .map(grade -> {
                    NotificationDTO.GradeInfo info = new NotificationDTO.GradeInfo();
                    info.setGrade(grade);
                    info.setDisplayName(grade + "级");
                    return info;
                })
                .collect(Collectors.toList());
    }
    
    /**
     * 获取班级列表（包含年级信息）
     * 只返回已注册学生的班级，确保数据准确性
     * 
     * @param keyword 搜索关键词（可选，用于搜索班级名称）
     * @return 班级列表
     */
    @Transactional(readOnly = true)
    public List<NotificationDTO.ClassInfo> getClassList(String keyword) {
        // 获取所有已注册的学生用户（这是数据源）
        List<User> students = userRepository.findByRoleAndStatus("student", 1);
        
        // 构建班级信息（班级名 + 年级）
        // 使用"年级-班级"作为key，避免不同年级的同名班级冲突
        Map<String, NotificationDTO.ClassInfo> classMap = new HashMap<>();
        
        for (User student : students) {
            // 提取年级（从学号中）
            String grade = "";
            if (student.getStudentId() != null && student.getStudentId().length() >= 4) {
                String gradePrefix = student.getStudentId().substring(0, 4);
                if (gradePrefix.startsWith("20")) {
                    grade = gradePrefix;
                }
            }
            
            // 如果无法提取年级，跳过该学生（不显示未知年级）
            if (grade.isEmpty()) {
                continue;
            }
            
            // 通过学号查找学生信息，获取班级名称
            String className = null;
            Optional<StudentInfo> studentInfoOpt = studentInfoRepository.findByStudentId(student.getStudentId());
            if (studentInfoOpt.isPresent()) {
                StudentInfo studentInfo = studentInfoOpt.get();
                if (studentInfo.getStatus() == 1 && 
                    studentInfo.getClassName() != null && 
                    !studentInfo.getClassName().trim().isEmpty()) {
                    className = studentInfo.getClassName().trim();
                }
            }
            
            // 如果没有班级信息，跳过该学生
            if (className == null || className.isEmpty()) {
                continue;
            }
            
            // 如果有关键词，进行过滤
            if (keyword != null && !keyword.trim().isEmpty()) {
                String keywordLower = keyword.trim().toLowerCase();
                if (!className.toLowerCase().contains(keywordLower) && 
                    !grade.contains(keyword.trim())) {
                    continue;
                }
            }
            
            // 使用"年级-班级"作为key，避免不同年级的同名班级冲突
            String key = grade + "-" + className;
            if (!classMap.containsKey(key)) {
                NotificationDTO.ClassInfo classInfo = new NotificationDTO.ClassInfo();
                classInfo.setClassName(className);
                classInfo.setGrade(grade);
                classInfo.setDisplayName(grade + "级-" + className);
                classMap.put(key, classInfo);
            }
        }
        
        // 转换为列表并排序
        return classMap.values().stream()
                .sorted((a, b) -> {
                    // 先按年级排序（降序，新的在前），再按班级名排序
                    int gradeCompare = b.getGrade().compareTo(a.getGrade());
                    if (gradeCompare != 0) {
                        return gradeCompare;
                    }
                    return a.getClassName().compareTo(b.getClassName());
                })
                .collect(Collectors.toList());
    }
}

