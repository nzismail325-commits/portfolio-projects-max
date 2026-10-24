/**
 * 文件说明：通用组件：封装统一返回体Result等公共结构。
 */
package com.campus.lowcarbon.common;

import lombok.Data;

/**
 * 统一响应结果类
 * 
 * @author Campus Team
 */
@Data
public class Result<T> {
    
    private Integer code; // 状态码：200-成功，其他-失败
    private String message; // 响应消息
    private T data; // 响应数据
    
    /**
     * 成功响应（无数据）
     */
    public static <T> Result<T> success() {
        Result<T> result = new Result<>();
        result.setCode(200);
        result.setMessage("操作成功");
        return result;
    }
    
    /**
     * 成功响应（带数据）
     */
    public static <T> Result<T> success(T data) {
        Result<T> result = new Result<>();
        result.setCode(200);
        result.setMessage("操作成功");
        result.setData(data);
        return result;
    }
    
    /**
     * 成功响应（自定义消息，无数据）
     */
    public static Result<Void> success(String message) {
        Result<Void> result = new Result<>();
        result.setCode(200);
        result.setMessage(message);
        return result;
    }
    
    /**
     * 成功响应（自定义消息，带数据）
     */
    public static <T> Result<T> success(String message, T data) {
        Result<T> result = new Result<>();
        result.setCode(200);
        result.setMessage(message);
        result.setData(data);
        return result;
    }
    
    /**
     * 失败响应
     */
    public static <T> Result<T> error(String message) {
        Result<T> result = new Result<>();
        result.setCode(500);
        result.setMessage(message);
        return result;
    }
    
    /**
     * 失败响应（自定义状态码）
     */
    public static <T> Result<T> error(Integer code, String message) {
        Result<T> result = new Result<>();
        result.setCode(code);
        result.setMessage(message);
        return result;
    }
}

