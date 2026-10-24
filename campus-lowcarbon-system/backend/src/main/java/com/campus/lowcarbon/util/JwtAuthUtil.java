/**
 * 文件说明：工具类：提供JWT/JSON等通用能力，供Controller/Service复用。
 */
package com.campus.lowcarbon.util;

import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * JWT认证工具类
 * 用于从请求中提取用户信息
 * 
 * @author Campus Team
 */
@Component
public class JwtAuthUtil {
    
    private final JwtUtil jwtUtil;
    
    public JwtAuthUtil(JwtUtil jwtUtil) {
        this.jwtUtil = jwtUtil;
    }
    
    /**
     * 从请求中获取Token
     * 
     * @param request HTTP请求
     * @return Token字符串
     */
    public String getTokenFromRequest(HttpServletRequest request) {
        String bearerToken = request.getHeader("Authorization");
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith("Bearer ")) {
            return bearerToken.substring(7);
        }
        return null;
    }
    
    /**
     * 从请求中获取用户角色
     * 
     * @param request HTTP请求
     * @return 用户角色（admin/student）
     */
    public String getRoleFromRequest(HttpServletRequest request) {
        String token = getTokenFromRequest(request);
        if (token != null && jwtUtil.validateToken(token)) {
            return jwtUtil.getRoleFromToken(token);
        }
        return null;
    }
    
    /**
     * 检查是否为管理员
     * 
     * @param request HTTP请求
     * @return 是否为管理员
     */
    public boolean isAdmin(HttpServletRequest request) {
        String role = getRoleFromRequest(request);
        return "admin".equals(role);
    }
    
    /**
     * 从请求中获取学号
     * 
     * @param request HTTP请求
     * @return 学号
     */
    public String getStudentIdFromRequest(HttpServletRequest request) {
        String token = getTokenFromRequest(request);
        if (token != null && jwtUtil.validateToken(token)) {
            return jwtUtil.getStudentIdFromToken(token);
        }
        return null;
    }
}

