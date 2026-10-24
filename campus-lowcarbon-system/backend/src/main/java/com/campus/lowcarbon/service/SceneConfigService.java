/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.SceneConfigDTO;
import com.campus.lowcarbon.entity.SceneConfig;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.SceneConfigRepository;
import com.campus.lowcarbon.util.JsonUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 场景配置服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class SceneConfigService {
    
    private final SceneConfigRepository sceneConfigRepository;
    
    /**
     * 获取所有场景配置
     * 
     * @return 场景配置列表
     */
    @Transactional(readOnly = true)
    public List<SceneConfigDTO> getAllConfigs() {
        List<SceneConfig> configs = sceneConfigRepository.findAll();
        return configs.stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }
    
    /**
     * 根据场景类型获取配置
     * 
     * @param sceneType 场景类型
     * @return 场景配置
     */
    @Transactional(readOnly = true)
    public SceneConfigDTO getConfigBySceneType(String sceneType) {
        SceneConfig config = sceneConfigRepository.findBySceneType(sceneType)
                .orElseThrow(() -> new BusinessException("场景配置不存在: " + sceneType));
        return convertToDTO(config);
    }
    
    /**
     * 更新场景配置（仅管理员）
     * 
     * @param sceneType 场景类型
     * @param dto 配置DTO
     * @return 更新后的配置
     */
    @Transactional
    public SceneConfigDTO updateConfig(String sceneType, SceneConfigDTO dto) {
        SceneConfig config = sceneConfigRepository.findBySceneType(sceneType)
                .orElseThrow(() -> new BusinessException("场景配置不存在: " + sceneType));
        
        // 更新配置字段
        if (dto.getIcon() != null) {
            config.setIcon(dto.getIcon());
        }
        if (dto.getTitle() != null) {
            config.setTitle(dto.getTitle());
        }
        if (dto.getTag() != null) {
            config.setTag(dto.getTag());
        }
        if (dto.getTagType() != null) {
            config.setTagType(dto.getTagType());
        }
        if (dto.getRewardPoints() != null) {
            config.setRewardPoints(dto.getRewardPoints());
        }
        if (dto.getCarbonReduction() != null) {
            config.setCarbonReduction(dto.getCarbonReduction());
        }
        if (dto.getDailyLimit() != null) {
            config.setDailyLimit(dto.getDailyLimit());
        }
        if (dto.getBonusStep() != null) {
            config.setBonusStep(dto.getBonusStep());
        }
        if (dto.getBonusPercentage() != null) {
            config.setBonusPercentage(dto.getBonusPercentage());
        }
        if (dto.getRequirementText() != null) {
            config.setRequirementText(dto.getRequirementText());
        }
        if (dto.getMinValue() != null) {
            config.setMinValue(dto.getMinValue());
        }
        if (dto.getUnit() != null) {
            config.setUnit(dto.getUnit());
        }
        if (dto.getKeywords() != null) {
            config.setKeywords(JsonUtil.listToJson(dto.getKeywords()));
        }
        if (dto.getExcludeKeywords() != null) {
            config.setExcludeKeywords(JsonUtil.listToJson(dto.getExcludeKeywords()));
        }
        
        // 保存更新
        SceneConfig savedConfig = sceneConfigRepository.save(config);
        return convertToDTO(savedConfig);
    }
    
    /**
     * 将实体转换为DTO
     * 
     * @param config 场景配置实体
     * @return 场景配置DTO
     */
    private SceneConfigDTO convertToDTO(SceneConfig config) {
        SceneConfigDTO dto = new SceneConfigDTO();
        dto.setSceneType(config.getSceneType());
        dto.setIcon(config.getIcon());
        dto.setTitle(config.getTitle());
        dto.setTag(config.getTag());
        dto.setTagType(config.getTagType());
        dto.setRewardPoints(config.getRewardPoints());
        dto.setCarbonReduction(config.getCarbonReduction());
        dto.setDailyLimit(config.getDailyLimit());
        dto.setBonusStep(config.getBonusStep());
        dto.setBonusPercentage(config.getBonusPercentage());
        dto.setRequirementText(config.getRequirementText());
        dto.setMinValue(config.getMinValue());
        dto.setUnit(config.getUnit());
        dto.setKeywords(JsonUtil.jsonToList(config.getKeywords()));
        dto.setExcludeKeywords(JsonUtil.jsonToList(config.getExcludeKeywords()));
        return dto;
    }
}

