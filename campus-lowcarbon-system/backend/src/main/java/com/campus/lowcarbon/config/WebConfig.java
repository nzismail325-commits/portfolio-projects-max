/**
 * 文件说明：配置类：Web相关配置（CORS、静态资源映射、拦截器注册等）。
 */
package com.campus.lowcarbon.config;

import com.campus.lowcarbon.interceptor.JwtAuthenticationInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.nio.file.Paths;

/**
 * Web配置类
 * 配置静态资源访问和HTTP客户端
 * 
 * @author Campus Team
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {
    
    @Value("${file.upload.path:uploads}")
    private String uploadPath;
    
    @Value("${file.upload.url-prefix:/api/uploads}")
    private String urlPrefix;

    @Autowired
    private JwtAuthenticationInterceptor jwtAuthenticationInterceptor;
    
    /**
     * 配置RestTemplate Bean，用于HTTP请求（如调用百度地图API）
     * 
     * @return RestTemplate实例
     */
    @Bean
    public RestTemplate restTemplate() {
        return new RestTemplate();
    }
    
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // 配置上传文件的访问路径
        // 注意：由于context-path是/api，所以映射规则需要去掉/api前缀
        String uploadDir = Paths.get(uploadPath).toAbsolutePath().toString();
        
        // 如果urlPrefix包含/api，去掉它（因为context-path会自动添加）
        String handlerPath = urlPrefix.startsWith("/api") 
            ? urlPrefix.substring(4)  // 去掉 "/api"
            : urlPrefix;
        
        registry.addResourceHandler(handlerPath + "/**")
                .addResourceLocations("file:" + uploadDir + "/");
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 注册JWT认证拦截器
        registry.addInterceptor(jwtAuthenticationInterceptor)
                .addPathPatterns("/**") // 拦截所有请求
                .excludePathPatterns(
                    "/auth/**",          // 排除认证接口
                    "/error",            // 排除错误页面
                    "/uploads/**",       // 排除上传文件
                    "/api/uploads/**",   // 排除上传文件(API路径)
                    "/swagger-ui/**",    // 排除Swagger文档
                    "/v3/api-docs/**"    // 排除Swagger API文档
                );
    }
}
