/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 登录请求DTO
 * 
 * @author Campus Team
 */
@Data
public class LoginRequest {
    
    @NotBlank(message = "学号不能为空")
    private String studentId; // 学号
    
    @NotBlank(message = "密码不能为空")
    private String password; // 密码
}

