/**
 * 文件说明：数据访问层：Spring Data JPA Repository接口，封装对数据库表的查询/统计方法。
 */
package com.campus.lowcarbon.repository;

import com.campus.lowcarbon.entity.StudentInfo;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.Optional;

/**
 * 学生学号信息数据访问层
 * 
 * @author Campus Team
 */
@Repository
public interface StudentInfoRepository extends JpaRepository<StudentInfo, Long> {
    
    /**
     * 根据学号查找学生信息
     * 
     * @param studentId 学号
     * @return 学生信息对象
     */
    Optional<StudentInfo> findByStudentId(String studentId);
    
    /**
     * 检查学号是否存在且有效
     * 
     * @param studentId 学号
     * @param status 状态（1-有效）
     * @return 是否存在
     */
    boolean existsByStudentIdAndStatus(String studentId, Integer status);
    
    /**
     * 检查学号和姓名是否匹配且有效（用于注册验证）
     * 
     * @param studentId 学号
     * @param name 真实姓名
     * @param status 状态（1-有效）
     * @return 是否匹配
     */
    boolean existsByStudentIdAndNameAndStatus(String studentId, String name, Integer status);
}

