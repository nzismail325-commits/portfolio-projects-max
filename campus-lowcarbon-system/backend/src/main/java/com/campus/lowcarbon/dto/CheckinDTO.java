/**
 * 文件说明：传输对象：定义接口请求/响应的数据结构，避免直接暴露Entity并便于前后端对接。
 */
package com.campus.lowcarbon.dto;

import lombok.Data;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

/**
 * 打卡请求DTO
 * 
 * @author Campus Team
 */
@Data
public class CheckinDTO {
    
    /**
     * 场景类型：walk-健步走，ride-骑行，plate-光盘，transit-公共交通
     */
    @NotBlank(message = "场景类型不能为空")
    private String sceneType;
    
    /**
     * AI验证结果状态：APPROVED-已通过，REJECTED-已驳回，SUSPICIOUS-可疑
     */
    @NotBlank(message = "验证状态不能为空")
    private String status;
    
    /**
     * 验证原因/拒绝原因
     */
    private String verifyReason;
    
    /**
     * 验证步骤详情（JSON数组字符串）
     */
    private String verifySteps;
    
    /**
     * 图片MD5哈希值（用于重复检测）
     */
    private String imageHash;
    
    /**
     * 奖励积分（仅当status=APPROVED时有效）
     */
    private Integer rewardPoints;
    
    /**
     * 图片文件（用于上传）
     */
    @NotNull(message = "图片文件不能为空")
    private java.io.InputStream imageInputStream;
    
    /**
     * 图片文件名
     */
    private String imageFilename;
}

