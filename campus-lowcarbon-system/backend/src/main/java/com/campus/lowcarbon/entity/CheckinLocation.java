/**
 * 文件说明：实体层：JPA实体，映射数据库表字段，用于持久化与查询。
 */
package com.campus.lowcarbon.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 打卡位置记录实体类
 * 对应数据库表：checkin_location
 * 
 * @author Campus Team
 */
@Entity
@Table(name = "checkin_location")
@Data
public class CheckinLocation {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "user_id", nullable = false)
    private Long userId; // 用户ID
    
    @Column(name = "scene_type", nullable = false, length = 20)
    private String sceneType; // 场景类型：walk-健步走，ride-骑行，transit-公共交通
    
    @Column(name = "start_latitude", precision = 10, scale = 7)
    private BigDecimal startLatitude; // 起始纬度
    
    @Column(name = "start_longitude", precision = 10, scale = 7)
    private BigDecimal startLongitude; // 起始经度
    
    @Column(name = "start_address", length = 255)
    private String startAddress; // 起始地址（通过百度API逆地理编码获取）
    
    @Column(name = "start_time")
    private LocalDateTime startTime; // 开始打卡时间
    
    @Column(name = "end_latitude", precision = 10, scale = 7)
    private BigDecimal endLatitude; // 结束纬度
    
    @Column(name = "end_longitude", precision = 10, scale = 7)
    private BigDecimal endLongitude; // 结束经度
    
    @Column(name = "end_address", length = 255)
    private String endAddress; // 结束地址（通过百度API逆地理编码获取）
    
    @Column(name = "end_time")
    private LocalDateTime endTime; // 结束打卡时间
    
    @Column(name = "distance", precision = 10, scale = 2)
    private BigDecimal distance; // 计算出的距离（米，使用百度API计算）
    
    @Column(name = "status", length = 20)
    private String status = "IN_PROGRESS"; // 状态：IN_PROGRESS-进行中，COMPLETED-已完成，CANCELLED-已取消
    
    @Column(name = "checkin_id")
    private Long checkinId; // 关联的打卡记录ID（如果最终提交了打卡）
    
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 创建时间
    
    @Column(name = "updated_at")
    private LocalDateTime updatedAt; // 更新时间
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }
    
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}

