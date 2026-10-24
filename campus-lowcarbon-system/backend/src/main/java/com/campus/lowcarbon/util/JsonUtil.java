/**
 * 文件说明：工具类：提供JWT/JSON等通用能力，供Controller/Service复用。
 */
package com.campus.lowcarbon.util;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import java.util.ArrayList;
import java.util.List;

/**
 * JSON工具类
 * 用于处理JSON字符串和Java对象之间的转换
 * 
 * @author Campus Team
 */
@Slf4j
public class JsonUtil {
    
    private static final ObjectMapper objectMapper = new ObjectMapper();
    
    /**
     * 将JSON字符串转换为List<String>
     * 
     * @param json JSON字符串
     * @return List<String>
     */
    public static List<String> jsonToList(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<String>>() {});
        } catch (Exception e) {
            log.error("JSON转List失败: {}", json, e);
            return new ArrayList<>();
        }
    }
    
    /**
     * 将List<String>转换为JSON字符串
     * 
     * @param list List<String>
     * @return JSON字符串
     */
    public static String listToJson(List<String> list) {
        if (list == null || list.isEmpty()) {
            return "[]";
        }
        try {
            return objectMapper.writeValueAsString(list);
        } catch (Exception e) {
            log.error("List转JSON失败: {}", list, e);
            return "[]";
        }
    }
}

