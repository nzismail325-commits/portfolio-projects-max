/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.RiskControlDTO;
import com.campus.lowcarbon.entity.StudentInfo;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.StudentInfoRepository;
import com.campus.lowcarbon.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 用户风控服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class RiskControlService {
    
    private final UserRepository userRepository;
    private final StudentInfoRepository studentInfoRepository;
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");
    private static final int RISK_THRESHOLD = 5; // 风险阈值：>=5为高危
    
    /**
     * 获取用户风控列表
     * 
     * @param keyword 搜索关键词（学号或姓名，可选）
     * @param status 账号状态筛选（normal-正常，banned-已封禁，可选）
     * @return 用户风控列表响应
     */
    @Transactional(readOnly = true)
    public RiskControlDTO.UserRiskListResponse getUserRiskList(String keyword, String status) {
        // 获取所有学生用户
        List<User> users;
        
        if (keyword != null && !keyword.trim().isEmpty()) {
            // 有搜索关键词，进行模糊查询
            users = userRepository.findByRoleAndKeyword("student", keyword.trim());
        } else {
            // 无搜索关键词，获取所有学生
            users = userRepository.findByRole("student");
        }
        
        // 转换为DTO并计算风险等级
        List<RiskControlDTO.UserRiskInfo> userRiskInfos = users.stream()
                .map(this::convertToUserRiskInfo)
                .collect(Collectors.toList());
        
        // 状态筛选
        if (status != null && !status.trim().isEmpty()) {
            if ("banned".equals(status.trim())) {
                userRiskInfos = userRiskInfos.stream()
                        .filter(u -> "banned".equals(u.getStatus()))
                        .collect(Collectors.toList());
            } else if ("normal".equals(status.trim())) {
                userRiskInfos = userRiskInfos.stream()
                        .filter(u -> "normal".equals(u.getStatus()))
                        .collect(Collectors.toList());
            }
        }
        
        // 排序：按异常次数降序，然后按学号升序
        userRiskInfos.sort((a, b) -> {
            int countCompare = Integer.compare(b.getSuspiciousCount(), a.getSuspiciousCount());
            if (countCompare != 0) {
                return countCompare;
            }
            return a.getStudentId().compareTo(b.getStudentId());
        });
        
        // 计算统计数据
        RiskControlDTO.RiskStatistics statistics = calculateStatistics(userRiskInfos);
        
        // 构建响应
        RiskControlDTO.UserRiskListResponse response = new RiskControlDTO.UserRiskListResponse();
        response.setUsers(userRiskInfos);
        response.setStatistics(statistics);
        
        return response;
    }
    
    /**
     * 封禁用户
     * 
     * @param userId 用户ID
     * @param reason 封禁原因
     */
    @Transactional
    public void banUser(Long userId, String reason) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 不能封禁管理员
        if ("admin".equals(user.getRole())) {
            throw new BusinessException("不能封禁管理员账号");
        }
        
        // 如果已经封禁，无需重复操作
        if (user.getStatus() != null && user.getStatus() == 0) {
            throw new BusinessException("该用户已被封禁");
        }
        
        // 封禁用户
        user.setStatus(0); // 0-封禁
        
        // 限制封禁原因字数（最多200字）
        String finalReason;
        if (reason != null && !reason.trim().isEmpty()) {
            String trimmedReason = reason.trim();
            if (trimmedReason.length() > 200) {
                finalReason = trimmedReason.substring(0, 200);
            } else {
                finalReason = trimmedReason;
            }
        } else {
            finalReason = "管理员封禁";
        }
        user.setBanReason(finalReason);
        user.setBanTime(LocalDateTime.now());
        user.setRiskLevel("HIGH"); // 封禁用户标记为高危
        
        userRepository.save(user);
    }
    
    /**
     * 解封用户
     * 
     * @param userId 用户ID
     */
    @Transactional
    public void unbanUser(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 如果未封禁，无需操作
        if (user.getStatus() == null || user.getStatus() == 1) {
            throw new BusinessException("该用户未被封禁");
        }
        
        // 解封用户
        user.setStatus(1); // 1-正常
        user.setBanReason(null);
        user.setBanTime(null);
        
        // 根据异常次数重新计算风险等级
        if (user.getSuspiciousCount() != null) {
            if (user.getSuspiciousCount() >= RISK_THRESHOLD) {
                user.setRiskLevel("HIGH");
            } else if (user.getSuspiciousCount() > 0) {
                user.setRiskLevel("SUSPICIOUS");
            } else {
                user.setRiskLevel("SAFE");
            }
        } else {
            user.setRiskLevel("SAFE");
        }
        
        userRepository.save(user);
    }
    
    /**
     * 清除所有学生用户的Token（强制所有学生用户退出登录）
     * 通过增加所有学生用户的token_version来实现
     * 注意：管理员用户的token不会被清除
     * 
     * @return 被清除token的用户数量
     */
    @Transactional
    public int clearAllUserTokens() {
        // 只获取学生用户，排除管理员
        List<User> studentUsers = userRepository.findByRole("student");
        
        // 为每个学生用户增加token_version（使旧token失效）
        int count = 0;
        for (User user : studentUsers) {
            Long currentVersion = user.getTokenVersion() != null ? user.getTokenVersion() : 0L;
            user.setTokenVersion(currentVersion + 1);
            userRepository.save(user);
            count++;
        }
        
        return count;
    }
    
    /**
     * 将User实体转换为UserRiskInfo DTO
     */
    private RiskControlDTO.UserRiskInfo convertToUserRiskInfo(User user) {
        RiskControlDTO.UserRiskInfo info = new RiskControlDTO.UserRiskInfo();
        info.setId(user.getId());
        info.setStudentId(user.getStudentId());
        
        // 使用真实姓名（username），而不是昵称（nickname）
        info.setName(user.getUsername());
        
        info.setAvatar(user.getAvatar());
        info.setSuspiciousCount(user.getSuspiciousCount() != null ? user.getSuspiciousCount() : 0);
        
        // 计算风险等级
        if (user.getSuspiciousCount() != null && user.getSuspiciousCount() >= RISK_THRESHOLD) {
            info.setRiskLevel("HIGH");
        } else if (user.getSuspiciousCount() != null && user.getSuspiciousCount() > 0) {
            info.setRiskLevel("SUSPICIOUS");
        } else {
            info.setRiskLevel("SAFE");
        }
        
        // 账号状态：1-正常，0-封禁
        info.setStatus(user.getStatus() != null && user.getStatus() == 0 ? "banned" : "normal");
        
        // 封禁信息
        info.setBanReason(user.getBanReason());
        if (user.getBanTime() != null) {
            info.setBanTime(user.getBanTime().format(DATE_TIME_FORMATTER));
        }
        
        // 从student_info表获取学院和班级信息
        studentInfoRepository.findByStudentId(user.getStudentId())
                .ifPresent(studentInfo -> {
                    info.setCollege(studentInfo.getCollege());
                    info.setClassName(studentInfo.getClassName());
                });
        
        return info;
    }
    
    /**
     * 计算统计数据
     */
    private RiskControlDTO.RiskStatistics calculateStatistics(List<RiskControlDTO.UserRiskInfo> users) {
        RiskControlDTO.RiskStatistics statistics = new RiskControlDTO.RiskStatistics();
        
        int highRiskCount = 0;
        int suspiciousCount = 0;
        int bannedCount = 0;
        
        for (RiskControlDTO.UserRiskInfo user : users) {
            // 高危用户：异常次数 >= 5
            if (user.getSuspiciousCount() >= RISK_THRESHOLD) {
                highRiskCount++;
            }
            // 存疑用户：0 < 异常次数 < 5
            if (user.getSuspiciousCount() > 0 && user.getSuspiciousCount() < RISK_THRESHOLD) {
                suspiciousCount++;
            }
            // 已封禁用户
            if ("banned".equals(user.getStatus())) {
                bannedCount++;
            }
        }
        
        statistics.setHighRiskCount(highRiskCount);
        statistics.setSuspiciousCount(suspiciousCount);
        statistics.setBannedCount(bannedCount);
        
        return statistics;
    }
}

