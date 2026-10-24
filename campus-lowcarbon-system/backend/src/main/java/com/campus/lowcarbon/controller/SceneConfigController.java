/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.dto.SceneConfigDTO;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.service.SceneConfigService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 场景配置控制器
 * 处理打卡场景配置相关请求
 * 注意：前端路由已限制仅管理员可访问，后端不再进行权限验证
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/scene-config")
@RequiredArgsConstructor
public class SceneConfigController {
    
    private final SceneConfigService sceneConfigService;
    
    /**
     * 获取所有场景配置
     * 学生和管理员都可以访问
     * 
     * @return 场景配置列表
     */
    @GetMapping
    public Result<List<SceneConfigDTO>> getAllConfigs() {
        try {
            List<SceneConfigDTO> configs = sceneConfigService.getAllConfigs();
            return Result.success(configs);
        } catch (Exception e) {
            return Result.error(e.getMessage());
        }
    }
    
    /**
     * 根据场景类型获取配置
     * 学生和管理员都可以访问
     * 
     * @param sceneType 场景类型
     * @return 场景配置
     */
    @GetMapping("/{sceneType}")
    public Result<SceneConfigDTO> getConfigBySceneType(@PathVariable String sceneType) {
        try {
            SceneConfigDTO config = sceneConfigService.getConfigBySceneType(sceneType);
            return Result.success(config);
        } catch (Exception e) {
            return Result.error(e.getMessage());
        }
    }
    
    /**
     * 更新场景配置
     * 注意：前端路由已限制仅管理员可访问此页面
     * 
     * @param sceneType 场景类型
     * @param dto 配置DTO
     * @return 更新后的配置
     */
    @PutMapping("/{sceneType}")
    public Result<SceneConfigDTO> updateConfig(
            @PathVariable String sceneType,
            @Valid @RequestBody SceneConfigDTO dto) {
        try {
            // 确保sceneType一致
            dto.setSceneType(sceneType);
            SceneConfigDTO updatedConfig = sceneConfigService.updateConfig(sceneType, dto);
            return Result.success("配置更新成功", updatedConfig);
        } catch (BusinessException e) {
            return Result.error(e.getMessage());
        } catch (Exception e) {
            return Result.error("更新配置失败：" + e.getMessage());
        }
    }
}

