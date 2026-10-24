/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.UserTitle;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

/**
 * 用户称号关联数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface UserTitleRepository extends JpaRepository<UserTitle, Long> {
    
    /**
     * 根据用户ID查找所有称号
     */
    List<UserTitle> findByUserId(Long userId);
    
    /**
     * 根据用户ID和称号ID查找
     */
    Optional<UserTitle> findByUserIdAndTitleId(Long userId, Long titleId);
    
    /**
     * 查找用户在排行榜展示的称号
     */
    @Query("SELECT ut FROM UserTitle ut WHERE ut.userId = :userId AND ut.isDisplayed = 1 ORDER BY ut.id ASC")
    List<UserTitle> findDisplayedTitlesByUserId(@Param("userId") Long userId);
    
    /**
     * 查找所有在排行榜展示称号的用户
     */
    @Query("SELECT ut FROM UserTitle ut WHERE ut.isDisplayed = 1")
    List<UserTitle> findAllDisplayedTitles();
}

