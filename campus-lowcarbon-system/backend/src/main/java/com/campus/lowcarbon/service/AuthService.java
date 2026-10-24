/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.LoginRequest;
import com.campus.lowcarbon.dto.LoginResponse;
import com.campus.lowcarbon.dto.RegisterRequest;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.StudentInfoRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.util.JwtUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;

/**
 * 认证服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class AuthService {
    
    private final UserRepository userRepository;
    private final StudentInfoRepository studentInfoRepository;
    private final JwtUtil jwtUtil;
    
    /**
     * 用户登录
     * 
     * @param request 登录请求
     * @return 登录响应（包含Token和用户信息）
     */
    @Transactional
    public LoginResponse login(LoginRequest request) {
        // 查找用户
        User user = userRepository.findByStudentId(request.getStudentId())
                .orElseThrow(() -> new BusinessException("学号或密码错误"));
        
        // 验证密码（明文比较）
        if (!user.getPassword().equals(request.getPassword())) {
            throw new BusinessException("学号或密码错误");
        }
        
        // 检查账号状态
        if (user.getStatus() == 0) {
            // 如果有封禁原因，显示封禁原因；否则显示默认提示
            String banMessage;
            if (user.getBanReason() != null && !user.getBanReason().trim().isEmpty()) {
                String reason = user.getBanReason().trim();
                // 如果原因过长（超过100字），截断并添加省略号
                if (reason.length() > 100) {
                    reason = reason.substring(0, 100) + "...";
                }
                banMessage = String.format("账号已被封禁。封禁原因：%s。请联系管理员。", reason);
            } else {
                banMessage = "账号已被封禁，请联系管理员";
            }
            throw new BusinessException(banMessage);
        }
        
        // 更新最后登录时间
        user.setLastLoginTime(LocalDateTime.now());
        // 确保tokenVersion不为null
        if (user.getTokenVersion() == null) {
            user.setTokenVersion(0L);
        }
        userRepository.save(user);
        
        // 生成Token（包含tokenVersion）
        String token = jwtUtil.generateToken(user.getStudentId(), user.getRole(), user.getTokenVersion());
        
        // 构建响应
        LoginResponse.UserInfo userInfo = new LoginResponse.UserInfo(
                user.getUsername(),
                user.getStudentId(),
                user.getAvatar() != null ? user.getAvatar() : ""
        );
        
        return new LoginResponse(token, user.getRole(), userInfo);
    }
    
    /**
     * 用户注册
     * 
     * @param request 注册请求
     */
    @Transactional
    public void register(RegisterRequest request) {
        // 检查学号是否已注册
        if (userRepository.existsByStudentId(request.getStudentId())) {
            throw new BusinessException("该学号已被注册");
        }
        
        // 验证学号和姓名是否匹配（双重验证）
        boolean isValidStudent = studentInfoRepository.existsByStudentIdAndNameAndStatus(
                request.getStudentId(), request.getUsername(), 1);
        if (!isValidStudent) {
            throw new BusinessException("学号与姓名不匹配，请确认信息是否正确");
        }
        
        // 创建新用户
        User user = new User();
        user.setStudentId(request.getStudentId());
        user.setUsername(request.getUsername());
        user.setPassword(request.getPassword()); // 明文存储
        user.setRole("student"); // 默认角色为学生
        user.setStatus(1); // 默认状态为正常
        user.setPoints(0); // 初始积分为0
        
        // 保存用户
        userRepository.save(user);
    }
}

