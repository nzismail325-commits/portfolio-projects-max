/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.CheckinRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 打卡记录数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface CheckinRecordRepository extends JpaRepository<CheckinRecord, Long> {
    
    /**
     * 根据用户ID查找打卡记录
     * 
     * @param userId 用户ID
     * @return 打卡记录列表
     */
    List<CheckinRecord> findByUserId(Long userId);
    
    /**
     * 根据用户ID和场景类型查找打卡记录
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @return 打卡记录列表
     */
    List<CheckinRecord> findByUserIdAndSceneType(Long userId, String sceneType);
    
    /**
     * 根据用户ID和状态查找打卡记录
     * 
     * @param userId 用户ID
     * @param status 状态
     * @return 打卡记录列表
     */
    List<CheckinRecord> findByUserIdAndStatus(Long userId, String status);
    
    /**
     * 查找用户今日的打卡记录
     * 
     * @param userId 用户ID
     * @param startTime 今日开始时间
     * @param endTime 今日结束时间
     * @return 打卡记录列表
     */
    @Query("SELECT c FROM CheckinRecord c WHERE c.userId = :userId AND c.submitTime >= :startTime AND c.submitTime < :endTime ORDER BY c.submitTime DESC")
    List<CheckinRecord> findTodayRecords(@Param("userId") Long userId, 
                                         @Param("startTime") LocalDateTime startTime, 
                                         @Param("endTime") LocalDateTime endTime);
    
    /**
     * 根据图片MD5哈希值和场景类型查找打卡记录（用于重复检测）
     * 
     * @param imageHash 图片MD5哈希值
     * @param sceneType 场景类型
     * @return 打卡记录列表
     */
    List<CheckinRecord> findByImageHashAndSceneType(String imageHash, String sceneType);
    
    /**
     * 统计用户今日该场景的打卡次数（包括所有状态）
     * 
     * @param userId 用户ID
     * @param sceneType 场景类型
     * @param startTime 今日开始时间
     * @param endTime 今日结束时间
     * @return 打卡次数
     */
    @Query("SELECT COUNT(c) FROM CheckinRecord c WHERE c.userId = :userId AND c.sceneType = :sceneType AND c.submitTime >= :startTime AND c.submitTime < :endTime")
    long countTodayCheckinsByUserAndSceneType(@Param("userId") Long userId, 
                                               @Param("sceneType") String sceneType,
                                               @Param("startTime") LocalDateTime startTime, 
                                               @Param("endTime") LocalDateTime endTime);
}

