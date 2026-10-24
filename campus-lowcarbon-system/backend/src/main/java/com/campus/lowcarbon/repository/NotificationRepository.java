/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.Notification;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 通知消息数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface NotificationRepository extends JpaRepository<Notification, Long> {
    
    /**
     * 根据接收者ID查找通知（按创建时间降序）
     * 
     * @param receiverId 接收者ID
     * @param pageable 分页参数
     * @return 通知分页列表
     */
    Page<Notification> findByReceiverIdOrderByCreatedAtDesc(Long receiverId, Pageable pageable);
    
    /**
     * 根据接收者ID和类型查找通知（按创建时间降序）
     * 
     * @param receiverId 接收者ID
     * @param type 通知类型
     * @param pageable 分页参数
     * @return 通知分页列表
     */
    Page<Notification> findByReceiverIdAndTypeOrderByCreatedAtDesc(Long receiverId, String type, Pageable pageable);
    
    /**
     * 根据接收者ID和是否已读查找通知（按创建时间降序）
     * 
     * @param receiverId 接收者ID
     * @param isRead 是否已读（0-未读，1-已读）
     * @param pageable 分页参数
     * @return 通知分页列表
     */
    Page<Notification> findByReceiverIdAndIsReadOrderByCreatedAtDesc(Long receiverId, Integer isRead, Pageable pageable);
    
    /**
     * 根据接收者ID、类型和是否已读查找通知（按创建时间降序）
     * 
     * @param receiverId 接收者ID
     * @param type 通知类型
     * @param isRead 是否已读
     * @param pageable 分页参数
     * @return 通知分页列表
     */
    Page<Notification> findByReceiverIdAndTypeAndIsReadOrderByCreatedAtDesc(
            Long receiverId, String type, Integer isRead, Pageable pageable);
    
    /**
     * 统计接收者的未读通知数量
     * 
     * @param receiverId 接收者ID
     * @return 未读数量
     */
    long countByReceiverIdAndIsRead(Long receiverId, Integer isRead);
    
    /**
     * 根据接收者ID查找所有通知
     * 
     * @param receiverId 接收者ID
     * @return 通知列表
     */
    List<Notification> findByReceiverId(Long receiverId);
    
}

