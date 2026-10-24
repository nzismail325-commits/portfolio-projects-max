/**
 * 文件说明：启动入口：Spring Boot 启动类，负责应用启动与组件扫描。
 */
package com.campus.lowcarbon;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 校园低碳行为管理系统 - 主启动类
 * 
 * @author Campus Team
 * @date 2024
 */
@SpringBootApplication
public class LowcarbonSystemApplication {

    public static void main(String[] args) {
        SpringApplication.run(LowcarbonSystemApplication.class, args);
    }
}

