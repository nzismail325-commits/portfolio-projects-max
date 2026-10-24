/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.SceneConfig;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.Optional;

/**
 * 场景配置数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface SceneConfigRepository extends JpaRepository<SceneConfig, Long> {
    
    /**
     * 根据场景类型查找配置
     * 
     * @param sceneType 场景类型
     * @return 场景配置对象
     */
    Optional<SceneConfig> findBySceneType(String sceneType);
    
    /**
     * 检查场景类型是否存在
     * 
     * @param sceneType 场景类型
     * @return 是否存在
     */
    boolean existsBySceneType(String sceneType);
}

