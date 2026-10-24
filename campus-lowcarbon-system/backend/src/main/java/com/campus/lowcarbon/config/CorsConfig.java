/**
 * 文件说明：配置类：Web相关配置（CORS、静态资源映射、拦截器注册等）。
 */
package com.campus.lowcarbon.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.CorsFilter;

/**
 * 跨域配置类
 * 
 * @author Campus Team
 */
@Configuration
public class CorsConfig {
    
    @Bean
    public CorsFilter corsFilter() {
        CorsConfiguration config = new CorsConfiguration();
        
        // 允许所有源（开发环境，生产环境应指定具体域名）
        config.addAllowedOriginPattern("*");
        
        // 允许所有请求头
        config.addAllowedHeader("*");
        
        // 允许所有请求方法
        config.addAllowedMethod("*");
        
        // 允许携带凭证（如Cookie）
        config.setAllowCredentials(true);
        
        // 预检请求的有效期（秒）
        config.setMaxAge(3600L);
        
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        
        return new CorsFilter(source);
    }
}

