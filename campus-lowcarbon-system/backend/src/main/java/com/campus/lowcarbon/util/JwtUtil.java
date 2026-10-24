/**
 * 文件说明：工具类：提供JWT/JSON等通用能力，供Controller/Service复用。
 */
package com.campus.lowcarbon.util;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * JWT工具类
 * 
 * @author Campus Team
 */
@Component
public class JwtUtil {
    
    @Value("${jwt.secret}")
    private String secret;
    
    @Value("${jwt.expiration}")
    private Long expiration;
    
    /**
     * 生成JWT Token
     * 
     * @param studentId 学号
     * @param role 角色
     * @param tokenVersion Token版本号
     * @return Token字符串
     */
    public String generateToken(String studentId, String role, Long tokenVersion) {
        Date now = new Date();
        Date expiryDate = new Date(now.getTime() + expiration);
        
        SecretKey key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        
        return Jwts.builder()
                .subject(studentId)
                .claim("role", role)
                .claim("tokenVersion", tokenVersion != null ? tokenVersion : 0L)
                .issuedAt(now)
                .expiration(expiryDate)
                .signWith(key)
                .compact();
    }
    
    /**
     * 从Token中获取学号
     * 
     * @param token JWT Token
     * @return 学号
     */
    public String getStudentIdFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims != null ? claims.getSubject() : null;
    }
    
    /**
     * 从Token中获取角色
     * 
     * @param token JWT Token
     * @return 角色
     */
    public String getRoleFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims != null ? claims.get("role", String.class) : null;
    }
    
    /**
     * 从Token中获取Token版本号
     * 
     * @param token JWT Token
     * @return Token版本号
     */
    public Long getTokenVersionFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        if (claims != null) {
            Object version = claims.get("tokenVersion");
            if (version instanceof Number) {
                return ((Number) version).longValue();
            }
        }
        return 0L;
    }
    
    /**
     * 验证Token是否有效（不检查版本号）
     * 
     * @param token JWT Token
     * @return 是否有效
     */
    public boolean validateToken(String token) {
        try {
            Claims claims = getClaimsFromToken(token);
            return claims != null && !claims.getExpiration().before(new Date());
        } catch (Exception e) {
            return false;
        }
    }
    
    /**
     * 验证Token是否有效（检查版本号）
     * 
     * @param token JWT Token
     * @param currentTokenVersion 当前用户的Token版本号
     * @return 是否有效
     */
    public boolean validateToken(String token, Long currentTokenVersion) {
        try {
            Claims claims = getClaimsFromToken(token);
            if (claims == null || claims.getExpiration().before(new Date())) {
                return false;
            }
            // 检查Token版本号
            Long tokenVersion = getTokenVersionFromToken(token);
            return tokenVersion != null && tokenVersion.equals(currentTokenVersion);
        } catch (Exception e) {
            return false;
        }
    }
    
    /**
     * 从Token中获取Claims
     * 
     * @param token JWT Token
     * @return Claims对象
     */
    private Claims getClaimsFromToken(String token) {
        try {
            SecretKey key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
            return Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
        } catch (Exception e) {
            return null;
        }
    }
}

