/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.UserInfoDTO;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * 用户信息服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class UserService {
    
    private final UserRepository userRepository;
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");
    
    /**
     * 获取用户信息
     * 
     * @param userId 用户ID
     * @return 用户信息
     */
    @Transactional(readOnly = true)
    public UserInfoDTO.UserInfo getUserInfo(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        UserInfoDTO.UserInfo info = new UserInfoDTO.UserInfo();
        info.setStudentId(user.getStudentId());
        info.setUsername(user.getUsername());
        info.setNickname(user.getNickname() != null ? user.getNickname() : user.getUsername());
        info.setAvatar(user.getAvatar());
        info.setSignature(user.getSignature());
        info.setRole(user.getRole());
        
        if (user.getLastLoginTime() != null) {
            info.setLastLoginTime(user.getLastLoginTime().format(DATE_TIME_FORMATTER));
        } else {
            info.setLastLoginTime("从未登录");
        }
        
        // 设置是否已设置支付密码（仅学生）
        if ("student".equals(user.getRole())) {
            info.setHasPaymentPassword(
                user.getPaymentPassword() != null && !user.getPaymentPassword().isEmpty()
            );
        } else {
            info.setHasPaymentPassword(false);
        }
        
        return info;
    }
    
    /**
     * 更新个人信息
     * 
     * @param userId 用户ID
     * @param request 更新请求
     */
    @Transactional
    public void updateProfile(Long userId, UserInfoDTO.UpdateProfileRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 只有学生可以修改昵称，管理员传入昵称时直接忽略，不抛出异常
        if (request.getNickname() != null && !request.getNickname().trim().isEmpty()) {
            if ("student".equals(user.getRole())) {
                user.setNickname(request.getNickname().trim());
            }
            // 管理员角色时，忽略昵称字段，继续处理其他字段
        }
        
        if (request.getAvatar() != null) {
            user.setAvatar(request.getAvatar());
        }
        
        if (request.getSignature() != null) {
            user.setSignature(request.getSignature().trim());
        }
        
        userRepository.save(user);
    }
    
    /**
     * 修改登录密码
     * 
     * @param userId 用户ID
     * @param request 修改密码请求
     */
    @Transactional
    public void changePassword(Long userId, UserInfoDTO.ChangePasswordRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 验证原密码
        if (!user.getPassword().equals(request.getOldPassword())) {
            throw new BusinessException("原密码错误");
        }
        
        // 验证新密码和确认密码
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BusinessException("两次输入密码不一致");
        }
        
        // 验证密码长度
        if (request.getNewPassword().length() < 6) {
            throw new BusinessException("密码长度不能少于6位");
        }
        
        // 更新密码
        user.setPassword(request.getNewPassword());
        userRepository.save(user);
    }
    
    /**
     * 设置支付密码（仅学生）
     * 
     * @param userId 用户ID
     * @param request 设置支付密码请求
     */
    @Transactional
    public void setPaymentPassword(Long userId, UserInfoDTO.SetPaymentPasswordRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 只有学生可以设置支付密码
        if (!"student".equals(user.getRole())) {
            throw new BusinessException("只有学生可以设置支付密码");
        }
        
        // 验证新密码格式（6位数字）
        if (!request.getNewPassword().matches("^\\d{6}$")) {
            throw new BusinessException("支付密码必须是6位数字");
        }
        
        // 验证确认密码
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BusinessException("两次输入密码不一致");
        }
        
        // 如果已设置过支付密码，需要验证原密码
        if (user.getPaymentPassword() != null && !user.getPaymentPassword().isEmpty()) {
            if (request.getOldPassword() == null || request.getOldPassword().trim().isEmpty()) {
                throw new BusinessException("请先输入原支付密码");
            }
            if (!user.getPaymentPassword().equals(request.getOldPassword().trim())) {
                throw new BusinessException("原支付密码错误");
            }
        }
        // 首次设置时，oldPassword可以为空，不需要验证
        
        // 设置新支付密码
        user.setPaymentPassword(request.getNewPassword());
        userRepository.save(user);
    }
    
    /**
     * 关闭安全密码（删除支付密码）
     * 
     * @param userId 用户ID
     * @param paymentPassword 支付密码（用于验证）
     */
    @Transactional
    public void removePaymentPassword(Long userId, String paymentPassword) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 只有学生可以关闭安全密码
        if (!"student".equals(user.getRole())) {
            throw new BusinessException("只有学生可以关闭安全密码");
        }
        
        // 如果未设置支付密码，无需操作
        if (user.getPaymentPassword() == null || user.getPaymentPassword().trim().isEmpty()) {
            throw new BusinessException("您尚未设置支付密码");
        }
        
        // 验证支付密码
        if (paymentPassword == null || paymentPassword.trim().isEmpty()) {
            throw new BusinessException("请输入支付密码");
        }
        if (!user.getPaymentPassword().equals(paymentPassword.trim())) {
            throw new BusinessException("支付密码错误");
        }
        
        // 删除支付密码
        user.setPaymentPassword(null);
        userRepository.save(user);
    }
}

