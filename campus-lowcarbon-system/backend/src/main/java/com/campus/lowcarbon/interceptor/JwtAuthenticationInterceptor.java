/**
 * 文件说明：拦截器：在进入Controller前做统一校验（如JWT有效性、用户状态、强制下线等）。
 */
package com.campus.lowcarbon.interceptor;

import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.util.JwtAuthUtil;
import com.campus.lowcarbon.util.JwtUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.PrintWriter;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

/**
 * JWT认证拦截器
 * 用于增强安全性：在Token校验通过后，实时查询数据库检查用户状态
 */
@Component
@RequiredArgsConstructor
public class JwtAuthenticationInterceptor implements HandlerInterceptor {

    private final JwtAuthUtil jwtAuthUtil;
    private final JwtUtil jwtUtil;
    private final UserRepository userRepository;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        // 1. 获取Token
        String token = jwtAuthUtil.getTokenFromRequest(request);
        
        // 如果没有Token，放行（交给Controller处理401，或者由其他配置决定）
        // 这里为了兼容现有Controller手动检查的逻辑，我们只拦截 *携带了有效Token* 但 *用户状态异常* 的请求
        if (token == null || !jwtUtil.validateToken(token)) {
            return true;
        }

        // 2. 解析Token获取学号
        String studentId = jwtUtil.getStudentIdFromToken(token);
        if (studentId != null) {
            // 3. 实时查库检查用户状态
            Optional<User> userOpt = userRepository.findByStudentId(studentId);
            
            if (userOpt.isPresent()) {
                User user = userOpt.get();
                
                // 检查Token版本号是否匹配
                Long currentTokenVersion = user.getTokenVersion() != null ? user.getTokenVersion() : 0L;
                Long tokenVersion = jwtUtil.getTokenVersionFromToken(token);
                if (!currentTokenVersion.equals(tokenVersion)) {
                    // Token版本号不匹配，说明已被强制退出登录
                    response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                    response.setContentType("application/json;charset=UTF-8");
                    
                    Map<String, Object> result = new HashMap<>();
                    result.put("code", 401);
                    result.put("message", "登录状态已失效，请重新登录");
                    result.put("data", null);
                    
                    try (PrintWriter writer = response.getWriter()) {
                        writer.print(new ObjectMapper().writeValueAsString(result));
                    }
                    return false;
                }
                
                // 检查是否被封禁 (status: 1-正常, 0-封禁)
                if (user.getStatus() != null && user.getStatus() == 0) {
                    // 用户已被封禁，拦截请求
                    response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                    response.setContentType("application/json;charset=UTF-8");
                    
                    Map<String, Object> result = new HashMap<>();
                    result.put("code", 401);
                    result.put("message", "账号已被封禁，请联系管理员");
                    result.put("data", null);
                    
                    try (PrintWriter writer = response.getWriter()) {
                        writer.print(new ObjectMapper().writeValueAsString(result));
                    }
                    return false;
                }
            }
        }
        
        return true;
    }
}

