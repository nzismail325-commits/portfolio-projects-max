/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.CheckinLocation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * 打卡位置记录数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface CheckinLocationRepository extends JpaRepository<CheckinLocation, Long> {
    
    /**
     * 根据用户ID查找定位记录
     * 
     * @param userId 用户ID
     * @return 定位记录列表
     */
    List<CheckinLocation> findByUserId(Long userId);
    
    /**
     * 根据用户ID和场景类型查找定位记录
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @return 定位记录列表
     */
    List<CheckinLocation> findByUserIdAndSceneType(Long userId, String sceneType);
    
    /**
     * 根据用户ID、场景类型和状态查找定位记录
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param status 状态
     * @return 定位记录列表
     */
    List<CheckinLocation> findByUserIdAndSceneTypeAndStatus(Long userId, String sceneType, String status);
    
    /**
     * 查找用户当前进行中的定位记录（同一场景类型）
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param status 状态（IN_PROGRESS）
     * @return 定位记录（可选）
     */
    Optional<CheckinLocation> findFirstByUserIdAndSceneTypeAndStatusOrderByStartTimeDesc(
            Long userId, String sceneType, String status);
    
    /**
     * 根据打卡记录ID查找定位记录
     * 
     * @param checkinId 打卡记录ID
     * @return 定位记录（可选）
     */
    Optional<CheckinLocation> findByCheckinId(Long checkinId);
}

