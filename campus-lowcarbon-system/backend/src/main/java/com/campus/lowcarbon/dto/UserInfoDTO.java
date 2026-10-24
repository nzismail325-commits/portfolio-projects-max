/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;

/**
 * 用户信息DTO
 * 
 * @author Campus Team
 */
public class UserInfoDTO {
    
    /**
     * 用户信息响应
     */
    @Data
    public static class UserInfo {
        private String studentId; // 学号
        private String username; // 真实姓名
        private String nickname; // 昵称
        private String avatar; // 头像URL
        private String signature; // 个性签名
        private String lastLoginTime; // 最近登录时间
        private String role; // 角色
        private Boolean hasPaymentPassword; // 是否已设置支付密码（仅学生）
    }
    
    /**
     * 更新个人信息请求
     */
    @Data
    public static class UpdateProfileRequest {
        private String nickname; // 昵称
        private String avatar; // 头像URL
        private String signature; // 个性签名
    }
    
    /**
     * 修改登录密码请求
     */
    @Data
    public static class ChangePasswordRequest {
        private String oldPassword; // 原密码
        private String newPassword; // 新密码
        private String confirmPassword; // 确认密码
    }
    
    /**
     * 设置支付密码请求
     */
    @Data
    public static class SetPaymentPasswordRequest {
        private String oldPassword; // 原支付密码（可选，首次设置时为空）
        private String newPassword; // 新支付密码
        private String confirmPassword; // 确认支付密码
    }
}

