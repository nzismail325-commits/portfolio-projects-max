/**
 * 文件说明：业务层：承载核心业务规则与事务边界，组织多表读写与通知/风控等联动。
 */
package com.campus.lowcarbon.service;

import com.campus.lowcarbon.dto.MallDTO;
import com.campus.lowcarbon.entity.*;
import com.campus.lowcarbon.exception.BusinessException;
import com.campus.lowcarbon.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 商城服务类
 * 
 * @author Campus Team
 */
@Service
@RequiredArgsConstructor
public class MallService {
    
    private final UserRepository userRepository;
    private final TitleRepository titleRepository;
    private final BadgeRepository badgeRepository;
    private final UserTitleRepository userTitleRepository;
    private final UserBadgeRepository userBadgeRepository;
    
    /**
     * 获取 UserRepository（供 Controller 使用）
     */
    public UserRepository getUserRepository() {
        return userRepository;
    }
    
    /**
     * 获取用户资产信息
     * 
     * @param userId 用户ID
     * @return 用户资产信息
     */
    public MallDTO.UserAssets getUserAssets(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        // 计算已解锁称号数量
        List<UserTitle> userTitles = userTitleRepository.findByUserId(userId);
        long unlockedTitlesCount = userTitles.stream()
                .filter(ut -> ut.getLevel() > 0)
                .count();
        
        // 计算最高称号等级
        int maxTitleLevel = userTitles.stream()
                .mapToInt(UserTitle::getLevel)
                .max()
                .orElse(0);
        
        // 计算已拥有勋章数量
        long ownedBadgesCount = userBadgeRepository.findByUserId(userId).size();
        
        MallDTO.UserAssets assets = new MallDTO.UserAssets();
        assets.setPoints(user.getPoints());
        assets.setUnlockedTitlesCount((int) unlockedTitlesCount);
        assets.setMaxTitleLevel(maxTitleLevel);
        assets.setOwnedBadgesCount((int) ownedBadgesCount);
        assets.setTotalCheckins(user.getTotalCheckins());
        
        return assets;
    }
    
    /**
     * 获取用户统计数据
     * 
     * @param userId 用户ID
     * @return 用户统计数据
     */
    public MallDTO.UserStats getUserStats(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        MallDTO.UserStats stats = new MallDTO.UserStats();
        stats.setWalkCheckins(user.getWalkCheckins());
        stats.setPlateCheckins(user.getPlateCheckins());
        stats.setRideCheckins(user.getRideCheckins());
        stats.setTransitCheckins(user.getTransitCheckins());
        stats.setTotalCheckins(user.getTotalCheckins());
        
        return stats;
    }
    
    /**
     * 获取所有称号列表（包含用户拥有的信息）
     * 
     * @param userId 用户ID
     * @return 称号列表
     */
    public List<MallDTO.TitleInfo> getAllTitles(Long userId) {
        List<Title> titles = titleRepository.findAll();
        List<UserTitle> userTitles = userTitleRepository.findByUserId(userId);
        
        // 创建用户称号映射
        Map<Long, UserTitle> userTitleMap = userTitles.stream()
                .collect(Collectors.toMap(UserTitle::getTitleId, ut -> ut));
        
        return titles.stream().map(title -> {
            MallDTO.TitleInfo info = new MallDTO.TitleInfo();
            info.setId(title.getId());
            info.setName(title.getName());
            info.setIcon(title.getIcon());
            info.setBaseCost(title.getBaseCost());
            info.setMaxLevel(title.getMaxLevel());
            
            UserTitle userTitle = userTitleMap.get(title.getId());
            if (userTitle != null) {
                info.setLevel(userTitle.getLevel());
                info.setIsOwned(userTitle.getLevel() > 0);
                info.setIsEquipped(userTitle.getIsEquipped() == 1);
            } else {
                info.setLevel(0);
                info.setIsOwned(false);
                info.setIsEquipped(false);
            }
            
            // 计算下一级升级费用
            int currentLevel = info.getLevel();
            if (currentLevel < title.getMaxLevel()) {
                int nextCost = currentLevel == 0 
                    ? title.getBaseCost() 
                    : title.getBaseCost() * (int) Math.pow(2, currentLevel);
                info.setNextUpgradeCost(nextCost);
            } else {
                info.setNextUpgradeCost(0);
            }
            
            return info;
        }).collect(Collectors.toList());
    }
    
    /**
     * 获取所有勋章列表（包含用户拥有的信息）
     * 
     * @param userId 用户ID
     * @return 勋章列表
     */
    public List<MallDTO.BadgeInfo> getAllBadges(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        List<Badge> badges = badgeRepository.findAll();
        List<UserBadge> userBadges = userBadgeRepository.findByUserId(userId);
        
        // 创建用户勋章映射
        Map<Long, UserBadge> userBadgeMap = userBadges.stream()
                .collect(Collectors.toMap(UserBadge::getBadgeId, ub -> ub));
        
        return badges.stream().map(badge -> {
            MallDTO.BadgeInfo info = new MallDTO.BadgeInfo();
            info.setId(badge.getId());
            info.setName(badge.getName());
            info.setIcon(badge.getIcon());
            info.setType(badge.getType());
            info.setTarget(badge.getTarget());
            
            // 转换statKey从下划线格式到驼峰格式（数据库存储的是下划线格式，前端需要驼峰格式）
            String statKey = convertToCamelCase(badge.getStatKey());
            info.setStatKey(statKey);
            info.setDescription(badge.getDescription());
            
            UserBadge userBadge = userBadgeMap.get(badge.getId());
            if (userBadge != null) {
                info.setIsOwned(true);
                info.setIsEquipped(userBadge.getIsEquipped() == 1);
            } else {
                info.setIsOwned(false);
                info.setIsEquipped(false);
            }
            
            // 计算当前进度（getStatValue内部会处理下划线格式）
            int currentProgress = getStatValue(user, badge.getStatKey());
            info.setCurrentProgress(currentProgress);
            
            // 计算进度百分比
            int percentage = badge.getTarget() > 0 
                ? Math.min((currentProgress * 100) / badge.getTarget(), 100)
                : 0;
            info.setProgressPercentage(percentage);
            
            return info;
        }).collect(Collectors.toList());
    }
    
    /**
     * 解锁/升级称号
     * 
     * @param userId 用户ID
     * @param titleId 称号ID
     * @param paymentPassword 支付密码（如果已设置支付密码则必填）
     * @return 操作后的称号信息
     */
    @Transactional
    public MallDTO.TitleInfo upgradeTitle(Long userId, Long titleId, String paymentPassword) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        Title title = titleRepository.findById(titleId)
                .orElseThrow(() -> new BusinessException("称号不存在"));
        
        // 如果用户已设置支付密码，必须验证支付密码
        if (user.getPaymentPassword() != null && !user.getPaymentPassword().trim().isEmpty()) {
            if (paymentPassword == null || paymentPassword.trim().isEmpty()) {
                throw new BusinessException("请输入支付密码");
            }
            if (!user.getPaymentPassword().equals(paymentPassword.trim())) {
                throw new BusinessException("支付密码错误");
            }
        }
        
        // 获取或创建用户称号关联
        Optional<UserTitle> userTitleOpt = userTitleRepository.findByUserIdAndTitleId(userId, titleId);
        UserTitle userTitle;
        
        if (userTitleOpt.isPresent()) {
            userTitle = userTitleOpt.get();
        } else {
            userTitle = new UserTitle();
            userTitle.setUserId(userId);
            userTitle.setTitleId(titleId);
            userTitle.setLevel(0);
            userTitle.setIsEquipped(0);
            userTitle.setIsDisplayed(0);
        }
        
        // 检查是否已满级
        if (userTitle.getLevel() >= title.getMaxLevel()) {
            throw new BusinessException("称号已达到最高等级");
        }
        
        // 计算升级费用
        int currentLevel = userTitle.getLevel();
        int cost = currentLevel == 0 
            ? title.getBaseCost() 
            : title.getBaseCost() * (int) Math.pow(2, currentLevel);
        
        // 检查积分是否足够
        if (user.getPoints() < cost) {
            throw new BusinessException("积分不足，需要 " + cost + " 积分");
        }
        
        // 扣除积分并升级
        user.setPoints(user.getPoints() - cost);
        userTitle.setLevel(userTitle.getLevel() + 1);
        
        // 如果是首次解锁，设置创建时间
        if (userTitle.getId() == null) {
            userTitle.setCreatedAt(LocalDateTime.now());
        }
        
        userRepository.save(user);
        userTitleRepository.save(userTitle);
        
        // 返回更新后的称号信息
        return buildTitleInfo(title, userTitle);
    }
    
    /**
     * 佩戴/卸下称号
     * 
     * @param userId 用户ID
     * @param titleId 称号ID
     * @return 操作后的称号信息
     */
    @Transactional
    public MallDTO.TitleInfo toggleEquipTitle(Long userId, Long titleId) {
        UserTitle userTitle = userTitleRepository.findByUserIdAndTitleId(userId, titleId)
                .orElseThrow(() -> new BusinessException("您尚未拥有该称号"));
        
        if (userTitle.getLevel() == 0) {
            throw new BusinessException("称号未解锁，无法佩戴");
        }
        
        // 切换佩戴状态
        userTitle.setIsEquipped(userTitle.getIsEquipped() == 1 ? 0 : 1);
        userTitleRepository.save(userTitle);
        
        Title title = titleRepository.findById(titleId)
                .orElseThrow(() -> new BusinessException("称号不存在"));
        
        return buildTitleInfo(title, userTitle);
    }
    
    /**
     * 解锁勋章（用户手动解锁）
     * 
     * @param userId 用户ID
     * @param badgeId 勋章ID
     * @return 操作后的勋章信息
     */
    @Transactional
    public MallDTO.BadgeInfo unlockBadge(Long userId, Long badgeId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        Badge badge = badgeRepository.findById(badgeId)
                .orElseThrow(() -> new BusinessException("勋章不存在"));
        
        // 检查是否已拥有
        Optional<UserBadge> userBadgeOpt = userBadgeRepository.findByUserIdAndBadgeId(userId, badgeId);
        if (userBadgeOpt.isPresent()) {
            throw new BusinessException("您已拥有该勋章");
        }
        
        // 检查是否达成解锁条件
        int currentValue = getStatValue(user, badge.getStatKey());
        if (currentValue < badge.getTarget()) {
            throw new BusinessException("未达成解锁条件，需要 " + badge.getTarget() + "，当前 " + currentValue);
        }
        
        // 创建用户勋章关联
        UserBadge userBadge = new UserBadge();
        userBadge.setUserId(userId);
        userBadge.setBadgeId(badgeId);
        userBadge.setIsEquipped(0);
        userBadge.setIsDisplayed(0);
        userBadge.setUnlockTime(LocalDateTime.now());
        userBadgeRepository.save(userBadge);
        
        // 返回更新后的勋章信息
        return buildBadgeInfo(badge, userBadge, user);
    }
    
    /**
     * 佩戴/卸下勋章
     * 
     * @param userId 用户ID
     * @param badgeId 勋章ID
     * @return 操作后的勋章信息
     */
    @Transactional
    public MallDTO.BadgeInfo toggleEquipBadge(Long userId, Long badgeId) {
        UserBadge userBadge = userBadgeRepository.findByUserIdAndBadgeId(userId, badgeId)
                .orElseThrow(() -> new BusinessException("您尚未拥有该勋章"));
        
        Badge badge = badgeRepository.findById(badgeId)
                .orElseThrow(() -> new BusinessException("勋章不存在"));
        
        // 如果要佩戴，需要先取消同系列其他勋章的佩戴状态
        if (userBadge.getIsEquipped() == 0) {
            List<UserBadge> sameTypeBadges = userBadgeRepository.findByUserId(userId).stream()
                    .filter(ub -> {
                        Badge b = badgeRepository.findById(ub.getBadgeId()).orElse(null);
                        return b != null && b.getType().equals(badge.getType());
                    })
                    .collect(Collectors.toList());
            
            for (UserBadge ub : sameTypeBadges) {
                ub.setIsEquipped(0);
                userBadgeRepository.save(ub);
            }
        }
        
        // 切换佩戴状态
        userBadge.setIsEquipped(userBadge.getIsEquipped() == 1 ? 0 : 1);
        userBadgeRepository.save(userBadge);
        
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new BusinessException("用户不存在"));
        
        return buildBadgeInfo(badge, userBadge, user);
    }
    
    /**
     * 根据统计字段名获取用户统计值
     * 支持下划线格式（walk_checkins）和驼峰格式（walkCheckins）
     */
    private int getStatValue(User user, String statKey) {
        // 统一转换为下划线格式进行匹配
        String normalizedKey = statKey.toLowerCase();
        
        // 支持两种格式：下划线格式和驼峰格式
        if ("walk_checkins".equals(normalizedKey) || "walkcheckins".equals(normalizedKey)) {
            return user.getWalkCheckins() != null ? user.getWalkCheckins() : 0;
        } else if ("plate_checkins".equals(normalizedKey) || "platecheckins".equals(normalizedKey)) {
            return user.getPlateCheckins() != null ? user.getPlateCheckins() : 0;
        } else if ("ride_checkins".equals(normalizedKey) || "ridecheckins".equals(normalizedKey)) {
            return user.getRideCheckins() != null ? user.getRideCheckins() : 0;
        } else if ("transit_checkins".equals(normalizedKey) || "transitcheckins".equals(normalizedKey)) {
            return user.getTransitCheckins() != null ? user.getTransitCheckins() : 0;
        } else if ("total_checkins".equals(normalizedKey) || "totalcheckins".equals(normalizedKey)) {
            return user.getTotalCheckins() != null ? user.getTotalCheckins() : 0;
        }
        return 0;
    }
    
    /**
     * 将下划线格式转换为驼峰格式
     * 例如：walk_checkins -> walkCheckins
     */
    private String convertToCamelCase(String snakeCase) {
        if (snakeCase == null || snakeCase.isEmpty()) {
            return snakeCase;
        }
        
        // 如果已经是驼峰格式，直接返回
        if (!snakeCase.contains("_")) {
            return snakeCase;
        }
        
        String[] parts = snakeCase.split("_");
        StringBuilder camelCase = new StringBuilder(parts[0]);
        
        for (int i = 1; i < parts.length; i++) {
            if (parts[i].length() > 0) {
                camelCase.append(Character.toUpperCase(parts[i].charAt(0)));
                if (parts[i].length() > 1) {
                    camelCase.append(parts[i].substring(1));
                }
            }
        }
        
        return camelCase.toString();
    }
    
    /**
     * 构建称号信息
     */
    private MallDTO.TitleInfo buildTitleInfo(Title title, UserTitle userTitle) {
        MallDTO.TitleInfo info = new MallDTO.TitleInfo();
        info.setId(title.getId());
        info.setName(title.getName());
        info.setIcon(title.getIcon());
        info.setBaseCost(title.getBaseCost());
        info.setMaxLevel(title.getMaxLevel());
        info.setLevel(userTitle.getLevel());
        info.setIsOwned(userTitle.getLevel() > 0);
        info.setIsEquipped(userTitle.getIsEquipped() == 1);
        
        int currentLevel = userTitle.getLevel();
        if (currentLevel < title.getMaxLevel()) {
            int nextCost = currentLevel == 0 
                ? title.getBaseCost() 
                : title.getBaseCost() * (int) Math.pow(2, currentLevel);
            info.setNextUpgradeCost(nextCost);
        } else {
            info.setNextUpgradeCost(0);
        }
        
        return info;
    }
    
    /**
     * 构建勋章信息
     */
    private MallDTO.BadgeInfo buildBadgeInfo(Badge badge, UserBadge userBadge, User user) {
        MallDTO.BadgeInfo info = new MallDTO.BadgeInfo();
        info.setId(badge.getId());
        info.setName(badge.getName());
        info.setIcon(badge.getIcon());
        info.setType(badge.getType());
        info.setTarget(badge.getTarget());
        // 转换statKey从下划线格式到驼峰格式（数据库存储的是下划线格式，前端需要驼峰格式）
        String statKey = convertToCamelCase(badge.getStatKey());
        info.setStatKey(statKey);
        info.setDescription(badge.getDescription());
        info.setIsOwned(userBadge != null);
        info.setIsEquipped(userBadge != null && userBadge.getIsEquipped() == 1);
        
        int currentProgress = getStatValue(user, badge.getStatKey());
        info.setCurrentProgress(currentProgress);
        
        int percentage = badge.getTarget() > 0 
            ? Math.min((currentProgress * 100) / badge.getTarget(), 100)
            : 0;
        info.setProgressPercentage(percentage);
        
        return info;
    }
}

