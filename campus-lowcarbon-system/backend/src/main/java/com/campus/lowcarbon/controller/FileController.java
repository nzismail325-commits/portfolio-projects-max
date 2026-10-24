/**
 * 文件说明：接口层：接收HTTP请求，做参数校验/鉴权信息提取，调用Service并返回统一Result。
 */
package com.campus.lowcarbon.controller;

import com.campus.lowcarbon.common.Result;
import com.campus.lowcarbon.service.MallService;
import com.campus.lowcarbon.util.JwtAuthUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

/**
 * 文件上传控制器
 * 
 * @author Campus Team
 */
@RestController
@RequestMapping("/file")
@RequiredArgsConstructor
public class FileController {
    
    private final MallService mallService;
    private final JwtAuthUtil jwtAuthUtil;
    
    @Value("${file.upload.path:uploads}")
    private String uploadPath;
    
    @Value("${file.upload.url-prefix:/uploads}")
    private String urlPrefix;
    
    /**
     * 上传头像
     * 
     * @param request HTTP请求
     * @param file 头像文件
     * @return 文件URL
     */
    @PostMapping("/avatar")
    public Result<String> uploadAvatar(
            HttpServletRequest request,
            @RequestParam("file") MultipartFile file) {
        try {
            Long userId = getCurrentUserId(request);
            if (userId == null) {
                return Result.<String>error(401, "未登录");
            }
            
            // 验证文件
            if (file == null || file.isEmpty()) {
                return Result.<String>error("请选择要上传的文件");
            }
            
            // 验证文件类型
            String contentType = file.getContentType();
            if (contentType == null || !contentType.startsWith("image/")) {
                return Result.<String>error("只能上传图片文件");
            }
            
            // 验证文件大小（2MB）
            if (file.getSize() > 2 * 1024 * 1024) {
                return Result.<String>error("图片大小不能超过2MB");
            }
            
            // 创建上传目录（使用绝对路径）
            Path uploadBasePath = Paths.get(uploadPath).toAbsolutePath();
            Path avatarDir = uploadBasePath.resolve("avatars");
            if (!Files.exists(avatarDir)) {
                Files.createDirectories(avatarDir);
            }
            
            // 获取用户当前头像URL，准备删除旧文件
            String oldAvatarUrl = null;
            try {
                com.campus.lowcarbon.entity.User user = mallService.getUserRepository().findById(userId).orElse(null);
                if (user != null && user.getAvatar() != null && !user.getAvatar().trim().isEmpty()) {
                    oldAvatarUrl = user.getAvatar();
                }
            } catch (Exception e) {
                // 忽略获取旧头像失败的错误，继续上传新头像
            }
            
            // 生成文件扩展名
            String originalFilename = file.getOriginalFilename();
            String extension = "";
            if (originalFilename != null && originalFilename.contains(".")) {
                extension = originalFilename.substring(originalFilename.lastIndexOf("."));
            }
            
            // 使用用户ID作为文件名，确保每个用户只有一个头像文件
            String filename = "avatar_" + userId + extension;
            
            // 删除旧头像文件（如果存在）
            if (oldAvatarUrl != null && !oldAvatarUrl.trim().isEmpty()) {
                try {
                    // 从URL中提取文件名
                    String oldFilename = extractFilenameFromUrl(oldAvatarUrl);
                    if (oldFilename != null) {
                        // 如果旧文件名与新文件名不同，删除旧文件
                        // 或者如果旧文件名也符合 avatar_用户ID.扩展名 格式，也删除（防止扩展名不同导致文件累积）
                        if (!oldFilename.equals(filename)) {
                            Path oldFilePath = avatarDir.resolve(oldFilename);
                            if (Files.exists(oldFilePath)) {
                                Files.delete(oldFilePath);
                            }
                        }
                        
                        // 额外检查：如果旧文件名格式是 avatar_用户ID.xxx，但扩展名不同，也删除
                        // 这样可以确保用户更换文件类型时，旧文件被删除
                        if (oldFilename.startsWith("avatar_" + userId + ".") && !oldFilename.equals(filename)) {
                            Path oldFilePath = avatarDir.resolve(oldFilename);
                            if (Files.exists(oldFilePath)) {
                                Files.delete(oldFilePath);
                            }
                        }
                    }
                } catch (Exception e) {
                    // 删除旧文件失败不影响新文件上传
                }
            }
            
            // 额外清理：删除该用户可能存在的其他头像文件（防止历史遗留文件）
            try {
                Files.list(avatarDir).forEach(path -> {
                    String fileName = path.getFileName().toString();
                    // 如果文件名以 avatar_用户ID. 开头，但不是当前文件名，则删除
                    if (fileName.startsWith("avatar_" + userId + ".") && !fileName.equals(filename)) {
                        try {
                            Files.delete(path);
                        } catch (Exception e) {
                            // 忽略删除失败
                        }
                    }
                });
            } catch (Exception e) {
                // 清理失败不影响新文件上传
            }
            
            // 保存新文件
            Path filePath = avatarDir.resolve(filename);
            file.transferTo(filePath.toFile());
            
            // 生成访问URL（注意：后端context-path是/api，所以URL前缀需要包含/api）
            String fileUrl = (urlPrefix.startsWith("/") ? "" : "/") + urlPrefix + "/avatars/" + filename;
            
            return Result.success("头像上传成功", fileUrl);
        } catch (IOException e) {
            return Result.<String>error("文件上传失败：" + e.getMessage());
        } catch (Exception e) {
            return Result.<String>error("上传失败：" + e.getMessage());
        }
    }
    
    /**
     * 从URL中提取文件名
     * 
     * @param url 文件URL
     * @return 文件名
     */
    private String extractFilenameFromUrl(String url) {
        if (url == null || url.trim().isEmpty()) {
            return null;
        }
        
        // 移除查询参数
        int queryIndex = url.indexOf('?');
        if (queryIndex > 0) {
            url = url.substring(0, queryIndex);
        }
        
        // 提取文件名（最后一个斜杠后的部分）
        int lastSlashIndex = url.lastIndexOf('/');
        if (lastSlashIndex >= 0 && lastSlashIndex < url.length() - 1) {
            return url.substring(lastSlashIndex + 1);
        }
        
        return null;
    }
    
    /**
     * 从请求中获取当前用户ID
     * 
     * @param request HTTP请求
     * @return 用户ID（如果未登录则返回null）
     */
    private Long getCurrentUserId(HttpServletRequest request) {
        String studentId = jwtAuthUtil.getStudentIdFromRequest(request);
        if (studentId == null) {
            return null;
        }
        
        return mallService.getUserRepository().findByStudentId(studentId)
                .map(user -> user.getId())
                .orElse(null);
    }
}

