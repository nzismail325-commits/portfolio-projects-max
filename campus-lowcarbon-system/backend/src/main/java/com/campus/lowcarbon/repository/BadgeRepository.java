/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.Badge;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * 勋章数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface BadgeRepository extends JpaRepository<Badge, Long> {
}

