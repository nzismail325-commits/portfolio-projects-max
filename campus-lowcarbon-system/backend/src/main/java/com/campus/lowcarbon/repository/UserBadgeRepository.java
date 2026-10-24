/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.UserBadge;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

/**
 * 用户勋章关联数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface UserBadgeRepository extends JpaRepository<UserBadge, Long> {
    
    /**
     * 根据用户ID查找所有勋章
     */
    List<UserBadge> findByUserId(Long userId);
    
    /**
     * 根据用户ID和勋章ID查找
     */
    Optional<UserBadge> findByUserIdAndBadgeId(Long userId, Long badgeId);
    
    /**
     * 查找用户在排行榜展示的勋章
     */
    @Query("SELECT ub FROM UserBadge ub WHERE ub.userId = :userId AND ub.isDisplayed = 1 ORDER BY ub.id ASC")
    List<UserBadge> findDisplayedBadgesByUserId(@Param("userId") Long userId);
    
    /**
     * 查找所有在排行榜展示勋章的用户
     */
    @Query("SELECT ub FROM UserBadge ub WHERE ub.isDisplayed = 1")
    List<UserBadge> findAllDisplayedBadges();
    
    /**
     * 统计用户拥有的勋章数量
     */
    @Query("SELECT COUNT(ub) FROM UserBadge ub WHERE ub.userId = :userId")
    Long countByUserId(@Param("userId") Long userId);
}

