/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 登录响应DTO
 * 
 * @author Campus Team
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class LoginResponse {
    
    private String token; // JWT Token
    private String role; // 角色：student-学生，admin-管理员
    private UserInfo userInfo; // 用户信息
    
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UserInfo {
        private String name; // 姓名
        private String studentId; // 学号
        private String avatar; // 头像
    }
}

