/**
 * 文件说明：异常体系：业务异常定义与全局异常处理，统一转换为Result返回。
 */
package com.campus.lowcarbon.exception;

/**
 * 业务异常类
 * 
 * @author Campus Team
 */
public class BusinessException extends RuntimeException {
    
    private Integer code;
    
    public BusinessException(String message) {
        super(message);
        this.code = 500;
    }
    
    public BusinessException(Integer code, String message) {
        super(message);
        this.code = code;
    }
    
    public Integer getCode() {
        return code;
    }
}

