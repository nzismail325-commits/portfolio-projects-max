/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.RankDTO;
import com.campus.lowcarbon.entity.*;
import com.campus.lowcarbon.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 排行榜服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class RankService {
    
    private final UserRepository userRepository;
    private final UserTitleRepository userTitleRepository;
    private final UserBadgeRepository userBadgeRepository;
    private final TitleRepository titleRepository;
    private final BadgeRepository badgeRepository;
    
    /**
     * 根据学号获取用户ID
     * 
     * @param studentId 学号
     * @return 用户ID
     */
    public Long getUserIdByStudentId(String studentId) {
        return userRepository.findByStudentId(studentId)
                .map(User::getId)
                .orElse(null);
    }
    
    /**
     * 获取积分排行榜
     * 
     * @param currentUserId 当前用户ID（可为null）
     * @param isAdmin 当前用户是否为管理员
     * @return 排行榜列表
     */
    public List<RankDTO> getPointsRank(Long currentUserId, boolean isAdmin) {
        // 获取所有学生用户，按积分降序排序
        List<User> users = userRepository.findByRoleAndStatus("student", 1);
        users.sort((a, b) -> Integer.compare(b.getPoints(), a.getPoints()));
        
        // 只取前100名
        List<User> topUsers = users.stream().limit(100).collect(Collectors.toList());
        
        return buildRankDTOList(topUsers, currentUserId, "points", null, isAdmin);
    }
    
    /**
     * 获取勋章排行榜
     * 
     * @param currentUserId 当前用户ID（可为null）
     * @param isAdmin 当前用户是否为管理员
     * @return 排行榜列表
     */
    public List<RankDTO> getBadgesRank(Long currentUserId, boolean isAdmin) {
        // 获取所有学生用户
        List<User> users = userRepository.findByRoleAndStatus("student", 1);
        
        // 计算每个用户的勋章数量
        Map<Long, Long> badgeCountMap = new HashMap<>();
        for (User user : users) {
            Long count = userBadgeRepository.countByUserId(user.getId());
            badgeCountMap.put(user.getId(), count);
        }
        
        // 按勋章数量降序排序
        users.sort((a, b) -> {
            Long countA = badgeCountMap.getOrDefault(a.getId(), 0L);
            Long countB = badgeCountMap.getOrDefault(b.getId(), 0L);
            return Long.compare(countB, countA);
        });
        
        // 只取前100名
        List<User> topUsers = users.stream().limit(100).collect(Collectors.toList());
        
        return buildRankDTOList(topUsers, currentUserId, "badges", null, isAdmin);
    }
    
    /**
     * 获取称号排行榜
     * 
     * @param currentUserId 当前用户ID（可为null）
     * @param isAdmin 当前用户是否为管理员
     * @return 排行榜列表
     */
    public List<RankDTO> getTitlesRank(Long currentUserId, boolean isAdmin) {
        // 获取所有学生用户
        List<User> users = userRepository.findByRoleAndStatus("student", 1);
        
        // 计算每个用户的称号分数
        Map<Long, Integer> titleScoreMap = new HashMap<>();
        for (User user : users) {
            int score = calculateTitleScore(user.getId());
            titleScoreMap.put(user.getId(), score);
        }
        
        // 按称号分数降序排序
        users.sort((a, b) -> {
            Integer scoreA = titleScoreMap.getOrDefault(a.getId(), 0);
            Integer scoreB = titleScoreMap.getOrDefault(b.getId(), 0);
            return Integer.compare(scoreB, scoreA);
        });
        
        // 只取前100名
        List<User> topUsers = users.stream().limit(100).collect(Collectors.toList());
        
        // 传递已计算的分数映射，避免重复计算
        return buildRankDTOList(topUsers, currentUserId, "titles", titleScoreMap, isAdmin);
    }
    
    /**
     * 计算用户的称号分数
     * 
     * @param userId 用户ID
     * @return 称号分数
     */
    private int calculateTitleScore(Long userId) {
        List<UserTitle> userTitles = userTitleRepository.findByUserId(userId);
        int score = 0;
        for (UserTitle ut : userTitles) {
            if (ut.getLevel() > 0) {
                // 称号分数 = 等级 * 权重
                score += ut.getLevel() * 10; // Lv.1=10分, Lv.2=20分, ..., Lv.5=50分
            }
        }
        return score;
    }
    
    /**
     * 获取打卡排行榜
     * 
     * @param currentUserId 当前用户ID（可为null）
     * @param isAdmin 当前用户是否为管理员
     * @return 排行榜列表
     */
    public List<RankDTO> getCheckinsRank(Long currentUserId, boolean isAdmin) {
        // 获取所有学生用户，按总打卡次数降序排序
        List<User> users = userRepository.findByRoleAndStatus("student", 1);
        users.sort((a, b) -> Integer.compare(b.getTotalCheckins(), a.getTotalCheckins()));
        
        // 只取前100名
        List<User> topUsers = users.stream().limit(100).collect(Collectors.toList());
        
        return buildRankDTOList(topUsers, currentUserId, "checkins", null, isAdmin);
    }
    
    /**
     * 构建排行榜DTO列表
     * 
     * @param users 用户列表
     * @param currentUserId 当前用户ID
     * @param rankType 排行榜类型
     * @param titleScoreMap 称号分数映射（可选，仅称号榜使用）
     * @param isAdmin 当前用户是否为管理员
     * @return DTO列表
     */
    private List<RankDTO> buildRankDTOList(List<User> users, Long currentUserId, String rankType, Map<Long, Integer> titleScoreMap, boolean isAdmin) {
        List<RankDTO> rankList = new ArrayList<>();
        
        for (User user : users) {
            RankDTO dto = new RankDTO();
            dto.setUserId(user.getId());
            
            // 设置昵称和真实姓名
            String nickname = user.getNickname();
            String realName = user.getUsername();
            dto.setNickname(nickname != null && !nickname.trim().isEmpty() ? nickname : realName);
            dto.setRealName(realName);
            
            // 默认显示昵称（如果昵称为空则显示真实姓名）
            dto.setName(dto.getNickname());
            
            // 学号仅管理员可见
            if (isAdmin) {
                dto.setStudentId(user.getStudentId());
            } else {
                dto.setStudentId(null);
            }
            
            dto.setAvatar(user.getAvatar());
            dto.setPoints(user.getPoints());
            dto.setCheckins(user.getTotalCheckins());
            dto.setIsCurrentUser(user.getId().equals(currentUserId));
            
            // 根据排行榜类型设置不同的值
            if ("points".equals(rankType)) {
                // 积分榜：不需要额外处理
            } else if ("badges".equals(rankType)) {
                // 勋章榜：计算勋章数量
                Long badgeCount = userBadgeRepository.countByUserId(user.getId());
                dto.setBadgesCount(badgeCount.intValue());
                
                // 获取展示的勋章
                List<UserBadge> displayedBadges = userBadgeRepository.findDisplayedBadgesByUserId(user.getId());
                if (!displayedBadges.isEmpty()) {
                    UserBadge displayedBadge = displayedBadges.get(0);
                    Badge badge = badgeRepository.findById(displayedBadge.getBadgeId()).orElse(null);
                    if (badge != null) {
                        RankDTO.FeaturedItem item = new RankDTO.FeaturedItem();
                        item.setName(badge.getName());
                        item.setIcon(badge.getIcon());
                        dto.setFeaturedItem(item);
                    }
                }
            } else if ("titles".equals(rankType)) {
                // 称号榜：使用已计算的分数（如果提供了映射），否则重新计算
                int score = titleScoreMap != null 
                    ? titleScoreMap.getOrDefault(user.getId(), 0)
                    : calculateTitleScore(user.getId());
                dto.setTitleScore(score);
                
                // 获取展示的称号
                List<UserTitle> displayedTitles = userTitleRepository.findDisplayedTitlesByUserId(user.getId());
                if (!displayedTitles.isEmpty()) {
                    UserTitle displayedTitle = displayedTitles.get(0);
                    Title title = titleRepository.findById(displayedTitle.getTitleId()).orElse(null);
                    if (title != null) {
                        RankDTO.FeaturedItem item = new RankDTO.FeaturedItem();
                        item.setName(title.getName());
                        item.setIcon(title.getIcon());
                        item.setLevel(displayedTitle.getLevel());
                        dto.setFeaturedItem(item);
                    }
                }
            } else if ("checkins".equals(rankType)) {
                // 打卡榜：不需要额外处理
            }
            
            // 设置趋势（暂时设为稳定，后续可根据历史数据计算）
            dto.setTrend("stable");
            
            rankList.add(dto);
        }
        
        return rankList;
    }
    
    /**
     * 设置排行榜展示（勋章或称号）
     * 
     * @param userId 用户ID
     * @param type 类型：badge 或 title
     * @param itemId 勋章ID或称号ID
     * @return 是否成功
     */
    @Transactional
    public boolean setDisplay(Long userId, String type, Long itemId) {
        if ("badge".equals(type)) {
            // 设置勋章展示
            // 先取消该用户所有勋章的展示状态
            List<UserBadge> userBadges = userBadgeRepository.findByUserId(userId);
            for (UserBadge ub : userBadges) {
                ub.setIsDisplayed(0);
                userBadgeRepository.save(ub);
            }
            
            // 设置指定勋章的展示状态
            Optional<UserBadge> userBadge = userBadgeRepository.findByUserIdAndBadgeId(userId, itemId);
            if (userBadge.isPresent()) {
                UserBadge ub = userBadge.get();
                ub.setIsDisplayed(1);
                userBadgeRepository.save(ub);
                return true;
            }
            return false;
        } else if ("title".equals(type)) {
            // 设置称号展示
            // 先取消该用户所有称号的展示状态
            List<UserTitle> userTitles = userTitleRepository.findByUserId(userId);
            for (UserTitle ut : userTitles) {
                ut.setIsDisplayed(0);
                userTitleRepository.save(ut);
            }
            
            // 设置指定称号的展示状态
            Optional<UserTitle> userTitle = userTitleRepository.findByUserIdAndTitleId(userId, itemId);
            if (userTitle.isPresent()) {
                UserTitle ut = userTitle.get();
                if (ut.getLevel() > 0) { // 只有已解锁的称号才能展示
                    ut.setIsDisplayed(1);
                    userTitleRepository.save(ut);
                    return true;
                }
            }
            return false;
        }
        return false;
    }
}
