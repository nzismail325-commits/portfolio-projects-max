/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.ReviewRecord;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 审核记录数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface ReviewRecordRepository extends JpaRepository<ReviewRecord, Long> {
    
    /**
     * 根据审核状态查找审核记录（按提交时间降序）
     * 
     * @param reviewStatus 审核状态
     * @return 审核记录列表
     */
    List<ReviewRecord> findByReviewStatusOrderBySubmitTimeDesc(String reviewStatus);
    
    /**
     * 根据审核状态查找审核记录（分页）
     * 
     * @param reviewStatus 审核状态
     * @param pageable 分页参数
     * @return 审核记录分页列表
     */
    Page<ReviewRecord> findByReviewStatusOrderBySubmitTimeDesc(String reviewStatus, Pageable pageable);
    
    /**
     * 根据审核状态和场景类型查找审核记录（分页）
     * 
     * @param reviewStatus 审核状态
     * @param sceneType 场景类型
     * @param pageable 分页参数
     * @return 审核记录分页列表
     */
    Page<ReviewRecord> findByReviewStatusAndSceneTypeOrderBySubmitTimeDesc(String reviewStatus, String sceneType, Pageable pageable);
    
    /**
     * 根据审核状态查找审核记录（限制数量）
     * 
     * @param reviewStatus 审核状态
     * @param pageable 分页参数
     * @return 审核记录列表
     */
    @Query("SELECT r FROM ReviewRecord r WHERE r.reviewStatus = :reviewStatus ORDER BY r.submitTime DESC")
    List<ReviewRecord> findByReviewStatusOrderBySubmitTimeDescLimit(@Param("reviewStatus") String reviewStatus, Pageable pageable);
    
    /**
     * 统计指定审核状态的记录数量
     * 
     * @param reviewStatus 审核状态
     * @return 记录数量
     */
    long countByReviewStatus(String reviewStatus);
    
    /**
     * 统计今日自动驳回数量（今日REJECTED状态，且reviewer_id为NULL）
     * 
     * @param startTime 今日开始时间
     * @param endTime 今日结束时间
     * @return 记录数量
     */
    @Query("SELECT COUNT(r) FROM ReviewRecord r WHERE r.reviewStatus = 'REJECTED' AND r.reviewerId IS NULL AND r.reviewTime >= :startTime AND r.reviewTime <= :endTime")
    long countTodayAutoRejected(@Param("startTime") LocalDateTime startTime, @Param("endTime") LocalDateTime endTime);
    
    /**
     * 统计今日人工复核通过数量（今日APPROVED状态，且reviewer_id不为NULL）
     * 
     * @param startTime 今日开始时间
     * @param endTime 今日结束时间
     * @return 记录数量
     */
    @Query("SELECT COUNT(r) FROM ReviewRecord r WHERE r.reviewStatus = 'APPROVED' AND r.reviewerId IS NOT NULL AND r.reviewTime >= :startTime AND r.reviewTime <= :endTime")
    long countTodayManualApproved(@Param("startTime") LocalDateTime startTime, @Param("endTime") LocalDateTime endTime);
    
    /**
     * 统计今日AI自动通过数量（今日APPROVED状态，且reviewer_id为NULL）
     * 
     * @param startTime 今日开始时间
     * @param endTime 今日结束时间
     * @return 记录数量
     */
    @Query("SELECT COUNT(r) FROM ReviewRecord r WHERE r.reviewStatus = 'APPROVED' AND r.reviewerId IS NULL AND r.reviewTime >= :startTime AND r.reviewTime <= :endTime")
    long countTodayAiApproved(@Param("startTime") LocalDateTime startTime, @Param("endTime") LocalDateTime endTime);
    
    /**
     * 根据用户ID查找审核记录
     * 
     * @param userId 用户ID
     * @return 审核记录列表
     */
    List<ReviewRecord> findByUserId(Long userId);
    
    /**
     * 根据打卡记录ID查找审核记录
     * 
     * @param checkinId 打卡记录ID
     * @return 审核记录列表
     */
    List<ReviewRecord> findByCheckinId(Long checkinId);
}

