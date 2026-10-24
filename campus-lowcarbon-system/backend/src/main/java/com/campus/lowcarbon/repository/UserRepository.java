/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.User;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

/**
 * 用户数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    
    /**
     * 根据学号查找用户
     * 
     * @param studentId 学号
     * @return 用户对象
     */
    Optional<User> findByStudentId(String studentId);
    
    /**
     * 检查学号是否存在
     * 
     * @param studentId 学号
     * @return 是否存在
     */
    boolean existsByStudentId(String studentId);
    
    /**
     * 根据角色和状态查找用户（分页）
     * 
     * @param role 角色
     * @param status 状态
     * @param pageable 分页参数
     * @return 用户列表
     */
    List<User> findByRoleAndStatus(String role, Integer status, Pageable pageable);
    
    /**
     * 根据角色和状态查找所有用户
     * 
     * @param role 角色
     * @param status 状态
     * @return 用户列表
     */
    List<User> findByRoleAndStatus(String role, Integer status);
    
    /**
     * 根据角色查找所有学生用户（用于风控管理）
     * 
     * @param role 角色（student）
     * @return 用户列表
     */
    List<User> findByRole(String role);
    
    /**
     * 根据学号或姓名模糊查询学生用户（用于风控搜索）
     * 
     * @param role 角色（student）
     * @param keyword 关键词（学号或姓名）
     * @return 用户列表
     */
    @Query("SELECT u FROM User u WHERE u.role = :role AND " +
           "(u.studentId LIKE %:keyword% OR u.username LIKE %:keyword% OR " +
           "(u.nickname IS NOT NULL AND u.nickname LIKE %:keyword%))")
    List<User> findByRoleAndKeyword(@Param("role") String role, @Param("keyword") String keyword);
    
    /**
     * 根据角色和状态查找学生用户（用于风控筛选）
     * 
     * @param role 角色（student）
     * @param status 状态（1-正常，0-封禁）
     * @return 用户列表
     */
    List<User> findByRoleAndStatusOrderBySuspiciousCountDesc(String role, Integer status);
}

