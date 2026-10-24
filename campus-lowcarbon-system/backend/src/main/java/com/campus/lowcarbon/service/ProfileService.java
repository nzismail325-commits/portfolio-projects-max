/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.ProfileDTO;
import com.campus.lowcarbon.entity.Badge;
import com.campus.lowcarbon.entity.SceneConfig;
import com.campus.lowcarbon.entity.Title;
import com.campus.lowcarbon.entity.User;
import com.campus.lowcarbon.entity.UserBadge;
import com.campus.lowcarbon.entity.UserTitle;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.BadgeRepository;
import com.campus.lowcarbon.repository.SceneConfigRepository;
import com.campus.lowcarbon.repository.TitleRepository;
import com.campus.lowcarbon.repository.UserBadgeRepository;
import com.campus.lowcarbon.repository.UserRepository;
import com.campus.lowcarbon.repository.UserTitleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 我的荣誉页面服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class ProfileService {
    
    private final UserRepository userRepository;
    private final TitleRepository titleRepository;
    private final BadgeRepository badgeRepository;
    private final UserTitleRepository userTitleRepository;
    private final UserBadgeRepository userBadgeRepository;
    private final SceneConfigRepository sceneConfigRepository;
    
    /**
     * 获取我的荣誉页面数据
     * 
     * @param userId 用户ID
     * @return 我的荣誉页面数据
     */
    public ProfileDTO.ProfileData getProfileData(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        ProfileDTO.ProfileData data = new ProfileDTO.ProfileData();
        
        // 用户资料
        ProfileDTO.UserProfile userProfile = new ProfileDTO.UserProfile();
        userProfile.setName(user.getUsername());
        userProfile.setNickname(user.getNickname() != null ? user.getNickname() : user.getUsername());
        userProfile.setStudentId(user.getStudentId());
        userProfile.setAvatar(user.getAvatar());
        userProfile.setPoints(user.getPoints() != null ? user.getPoints() : 0);
        userProfile.setTotalCheckins(user.getTotalCheckins() != null ? user.getTotalCheckins() : 0);
        
        // 根据用户各场景打卡次数和对应减碳量动态计算累计减碳量
        Map<String, SceneConfig> sceneConfigMap = sceneConfigRepository.findAll().stream()
                .collect(Collectors.toMap(SceneConfig::getSceneType, config -> config));
        
        BigDecimal totalCarbonReduction = BigDecimal.ZERO;
        
        // 健步走减碳量
        int walkCheckins = user.getWalkCheckins() != null ? user.getWalkCheckins() : 0;
        SceneConfig walkConfig = sceneConfigMap.get("walk");
        if (walkConfig != null && walkConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                walkConfig.getCarbonReduction().multiply(new BigDecimal(walkCheckins))
            );
        }
        
        // 骑行减碳量
        int rideCheckins = user.getRideCheckins() != null ? user.getRideCheckins() : 0;
        SceneConfig rideConfig = sceneConfigMap.get("ride");
        if (rideConfig != null && rideConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                rideConfig.getCarbonReduction().multiply(new BigDecimal(rideCheckins))
            );
        }
        
        // 光盘行动减碳量
        int plateCheckins = user.getPlateCheckins() != null ? user.getPlateCheckins() : 0;
        SceneConfig plateConfig = sceneConfigMap.get("plate");
        if (plateConfig != null && plateConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                plateConfig.getCarbonReduction().multiply(new BigDecimal(plateCheckins))
            );
        }
        
        // 公共交通减碳量
        int transitCheckins = user.getTransitCheckins() != null ? user.getTransitCheckins() : 0;
        SceneConfig transitConfig = sceneConfigMap.get("transit");
        if (transitConfig != null && transitConfig.getCarbonReduction() != null) {
            totalCarbonReduction = totalCarbonReduction.add(
                transitConfig.getCarbonReduction().multiply(new BigDecimal(transitCheckins))
            );
        }
        
        userProfile.setCarbonReduction(totalCarbonReduction.doubleValue());
        
        // 计算超过全校百分比
        int totalCheckins = user.getTotalCheckins() != null ? user.getTotalCheckins() : 0;
        
        // 查询所有学生用户（排除管理员）
        List<User> allStudents = userRepository.findByRoleAndStatus("student", 1);
        
        if (allStudents.isEmpty()) {
            // 如果没有其他学生，设为100%
            userProfile.setRankPercentage(100);
        } else {
            // 统计打卡次数比当前用户少的人数
            long usersBelowCount = allStudents.stream()
                    .filter(u -> {
                        int otherCheckins = u.getTotalCheckins() != null ? u.getTotalCheckins() : 0;
                        return otherCheckins < totalCheckins;
                    })
                    .count();
            
            // 计算百分比：超过的人数 / 总人数 * 100
            // 注意：如果只有1个用户，他应该超过100%的人（或者设为100%）
            int totalStudents = allStudents.size();
            int percentage = totalStudents == 1 
                ? 100  // 只有1个用户时，设为100%
                : (int) Math.round((usersBelowCount * 100.0) / totalStudents);
            
            // 确保百分比在0-100之间
            userProfile.setRankPercentage(Math.min(Math.max(percentage, 0), 100));
        }
        
        data.setUserProfile(userProfile);
        
        // 已拥有的称号列表（只返回已解锁的，level > 0）
        List<UserTitle> userTitles = userTitleRepository.findByUserId(userId);
        List<ProfileDTO.TitleInfo> titles = userTitles.stream()
                .filter(ut -> ut.getLevel() > 0)
                .map(ut -> {
                    Title title = titleRepository.findById(ut.getTitleId())
                            .orElse(null);
                    if (title == null) {
                        return null;
                    }
                    
                    ProfileDTO.TitleInfo info = new ProfileDTO.TitleInfo();
                    info.setId(title.getId());
                    info.setName(title.getName());
                    info.setIcon(title.getIcon());
                    info.setLevel(ut.getLevel());
                    info.setIsEquipped(ut.getIsEquipped() == 1);
                    return info;
                })
                .filter(info -> info != null)
                .collect(Collectors.toList());
        
        data.setTitles(titles);
        
        // 已拥有的勋章列表
        List<UserBadge> userBadges = userBadgeRepository.findByUserId(userId);
        List<ProfileDTO.BadgeInfo> badges = userBadges.stream()
                .map(ub -> {
                    Badge badge = badgeRepository.findById(ub.getBadgeId())
                            .orElse(null);
                    if (badge == null) {
                        return null;
                    }
                    
                    ProfileDTO.BadgeInfo info = new ProfileDTO.BadgeInfo();
                    info.setId(badge.getId());
                    info.setName(badge.getName());
                    info.setIcon(badge.getIcon());
                    info.setType(badge.getType());
                    info.setIsEquipped(ub.getIsEquipped() == 1);
                    return info;
                })
                .filter(info -> info != null)
                .collect(Collectors.toList());
        
        data.setBadges(badges);
        
        return data;
    }
}

