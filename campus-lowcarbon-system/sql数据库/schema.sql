-- ============================================
-- 智能低碳管理系统（校园场景） - 数据库设计
-- 数据库：MySQL 5.7+ / MySQL 8.0+
-- 字符集：utf8mb4
-- 排序规则：utf8mb4_unicode_ci
-- ============================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================
-- 创建数据库
-- ============================================

DROP DATABASE IF EXISTS `campus_lowcarbon_db`;

CREATE DATABASE `campus_lowcarbon_db` 
DEFAULT CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

USE `campus_lowcarbon_db`;

-- ============================================
-- 创建数据表
-- ============================================

-- 1. 学生学号信息表
DROP TABLE IF EXISTS `student_info`;
CREATE TABLE `student_info` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `student_id` varchar(20) NOT NULL COMMENT '学号',
  `name` varchar(50) NOT NULL COMMENT '真实姓名（用于注册验证）',
  `college` varchar(100) NULL DEFAULT NULL COMMENT '学院（管理员风控页面显示）',
  `class_name` varchar(50) NULL DEFAULT NULL COMMENT '班级（管理员风控页面显示）',
  `status` tinyint NULL DEFAULT 1 COMMENT '状态：1-有效，0-无效',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `student_id`(`student_id`),
  INDEX `idx_student_id`(`student_id`),
  INDEX `idx_status`(`status`),
  INDEX `idx_student_id_name`(`student_id`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学生学号信息表';

-- 2. 用户表
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `student_id` varchar(20) NOT NULL COMMENT '学号/管理员账号',
  `username` varchar(50) NOT NULL COMMENT '用户名（姓名）',
  `password` varchar(100) NOT NULL COMMENT '密码（明文存储）',
  `role` varchar(20) NOT NULL DEFAULT 'student' COMMENT '角色：student-学生，admin-管理员',
  `avatar` varchar(255) NULL DEFAULT NULL COMMENT '头像URL',
  `nickname` varchar(50) NULL DEFAULT NULL COMMENT '昵称',
  `signature` varchar(200) NULL DEFAULT NULL COMMENT '个性签名',
  `last_login_time` datetime NULL DEFAULT NULL COMMENT '最近登录时间',
  `status` tinyint NULL DEFAULT 1 COMMENT '账号状态：1-正常，0-封禁',
  `points` int NULL DEFAULT 0 COMMENT '积分数量',
  `walk_checkins` int NULL DEFAULT 0 COMMENT '健步走打卡次数',
  `plate_checkins` int NULL DEFAULT 0 COMMENT '光盘行动打卡次数',
  `ride_checkins` int NULL DEFAULT 0 COMMENT '骑行打卡次数',
  `transit_checkins` int NULL DEFAULT 0 COMMENT '公共交通打卡次数',
  `total_checkins` int NULL DEFAULT 0 COMMENT '总打卡次数',
  `suspicious_count` int NULL DEFAULT 0 COMMENT '异常次数',
  `risk_level` varchar(20) NULL DEFAULT 'SAFE' COMMENT '风险等级：SAFE-安全，SUSPICIOUS-存疑，HIGH-高危',
  `ban_reason` text NULL COMMENT '封禁原因',
  `ban_time` datetime NULL DEFAULT NULL COMMENT '封禁时间',
  `token_version` bigint NULL DEFAULT 0 COMMENT 'Token版本号（用于强制退出登录）',
  `payment_password` varchar(6) NULL DEFAULT NULL COMMENT '支付密码（6位数字，明文存储，仅学生）',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `student_id`(`student_id`),
  INDEX `idx_student_id`(`student_id`),
  INDEX `idx_role`(`role`),
  INDEX `idx_status`(`status`),
  INDEX `idx_points`(`points`),
  INDEX `idx_risk_level`(`risk_level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- 3. 场景配置表
DROP TABLE IF EXISTS `scene_config`;
CREATE TABLE `scene_config` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `scene_type` varchar(20) NOT NULL COMMENT '场景类型：walk-健步走，ride-骑行，plate-光盘，transit-公共交通',
  `icon` varchar(10) NULL DEFAULT NULL COMMENT '图标（emoji）',
  `title` varchar(50) NULL DEFAULT NULL COMMENT '标题',
  `tag` varchar(50) NULL DEFAULT NULL COMMENT '标签',
  `tag_type` varchar(20) NULL DEFAULT NULL COMMENT '标签类型',
  `reward_points` int NULL DEFAULT 10 COMMENT '奖励积分',
  `carbon_reduction` decimal(10, 4) NULL DEFAULT 0.3925 COMMENT '每次打卡减碳量（kg）',
  `daily_limit` int NULL DEFAULT 3 COMMENT '每天最多打卡次数（0表示不限制）',
  `bonus_step` decimal(10, 2) NULL DEFAULT NULL COMMENT '每多走多少步/多骑多少km增加积分（仅walk和ride有效，如1000步或1km）',
  `bonus_percentage` decimal(5, 2) NULL DEFAULT 10.00 COMMENT '每达到bonus_step时增加的积分百分比（如10表示增加10%）',
  `requirement_text` text NULL COMMENT '要求说明',
  `min_value` decimal(10, 2) NULL DEFAULT NULL COMMENT '最低要求值（步数/里程）',
  `unit` varchar(10) NULL DEFAULT NULL COMMENT '单位',
  `keywords` json NULL COMMENT 'AI判断关键词（数组）',
  `exclude_keywords` json NULL COMMENT '排除关键词（数组）',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `scene_type`(`scene_type`),
  INDEX `idx_scene_type`(`scene_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='场景配置表';

-- 4. 打卡记录表
DROP TABLE IF EXISTS `checkin_record`;
CREATE TABLE `checkin_record` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `scene_type` varchar(20) NOT NULL COMMENT '场景类型：walk-健步走，ride-骑行，plate-光盘，transit-公共交通',
  `image_url` varchar(255) NULL DEFAULT NULL COMMENT '凭证图片URL',
  `image_hash` varchar(64) NULL DEFAULT NULL COMMENT '图片MD5哈希值（用于重复检测）',
  `status` varchar(20) NULL DEFAULT 'PENDING' COMMENT '状态：PENDING-待审核，APPROVED-已通过，REJECTED-已驳回，SUSPICIOUS-可疑',
  `reward_points` int NULL DEFAULT 0 COMMENT '奖励积分',
  `verify_reason` text NULL COMMENT '验证原因/拒绝原因',
  `verify_steps` json NULL COMMENT '验证步骤详情（数组）',
  `submit_time` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '提交时间',
  `verify_time` datetime NULL DEFAULT NULL COMMENT '审核时间',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_scene_type`(`scene_type`),
  INDEX `idx_status`(`status`),
  INDEX `idx_submit_time`(`submit_time`),
  INDEX `idx_image_hash`(`image_hash`),
  CONSTRAINT `checkin_record_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='打卡记录表';

-- 5. 审核记录表
DROP TABLE IF EXISTS `review_record`;
CREATE TABLE `review_record` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `checkin_id` bigint NOT NULL COMMENT '打卡记录ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `scene_type` varchar(20) NOT NULL COMMENT '场景类型',
  `image_url` varchar(255) NULL DEFAULT NULL COMMENT '凭证图片URL',
  `reason` varchar(200) NULL DEFAULT NULL COMMENT '异常原因',
  `reason_type` varchar(20) NULL DEFAULT NULL COMMENT '原因类型：warning-警告，danger-危险，info-信息',
  `confidence` int NULL DEFAULT NULL COMMENT 'AI异常置信度（0-100）',
  `ai_reason` text NULL COMMENT 'AI详细原因说明',
  `review_status` varchar(20) NULL DEFAULT 'PENDING' COMMENT '审核状态：PENDING-待处理，APPROVED-已通过，REJECTED-已驳回',
  `reviewer_id` bigint NULL DEFAULT NULL COMMENT '审核人ID（管理员）',
  `review_comment` text NULL COMMENT '审核意见',
  `submit_time` datetime NULL DEFAULT NULL COMMENT '提交时间',
  `review_time` datetime NULL DEFAULT NULL COMMENT '审核时间',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_checkin_id`(`checkin_id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_review_status`(`review_status`),
  INDEX `idx_submit_time`(`submit_time`),
  INDEX `reviewer_id`(`reviewer_id`),
  CONSTRAINT `review_record_ibfk_1` FOREIGN KEY (`checkin_id`) REFERENCES `checkin_record` (`id`) ON DELETE CASCADE,
  CONSTRAINT `review_record_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `review_record_ibfk_3` FOREIGN KEY (`reviewer_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审核记录表';

-- 6. 打卡位置记录表（定位辅助功能）
DROP TABLE IF EXISTS `checkin_location`;
CREATE TABLE `checkin_location` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `scene_type` varchar(20) NOT NULL COMMENT '场景类型：walk-健步走，ride-骑行，transit-公共交通',
  `start_latitude` decimal(10, 7) NULL DEFAULT NULL COMMENT '起始纬度',
  `start_longitude` decimal(10, 7) NULL DEFAULT NULL COMMENT '起始经度',
  `start_address` varchar(255) NULL DEFAULT NULL COMMENT '起始地址（通过百度API逆地理编码获取）',
  `start_time` datetime NULL DEFAULT NULL COMMENT '开始打卡时间',
  `end_latitude` decimal(10, 7) NULL DEFAULT NULL COMMENT '结束纬度',
  `end_longitude` decimal(10, 7) NULL DEFAULT NULL COMMENT '结束经度',
  `end_address` varchar(255) NULL DEFAULT NULL COMMENT '结束地址（通过百度API逆地理编码获取）',
  `end_time` datetime NULL DEFAULT NULL COMMENT '结束打卡时间',
  `distance` decimal(10, 2) NULL DEFAULT NULL COMMENT '计算出的距离（米，使用百度API计算）',
  `status` varchar(20) NULL DEFAULT 'IN_PROGRESS' COMMENT '状态：IN_PROGRESS-进行中，COMPLETED-已完成，CANCELLED-已取消',
  `checkin_id` bigint NULL DEFAULT NULL COMMENT '关联的打卡记录ID（如果最终提交了打卡）',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_scene_type`(`scene_type`),
  INDEX `idx_status`(`status`),
  INDEX `idx_start_time`(`start_time`),
  INDEX `idx_checkin_id`(`checkin_id`),
  INDEX `idx_user_scene_status`(`user_id`, `scene_type`, `status`),
  CONSTRAINT `checkin_location_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `checkin_location_ibfk_2` FOREIGN KEY (`checkin_id`) REFERENCES `checkin_record` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='打卡位置记录表（定位辅助功能）';

-- 7. 通知消息表
DROP TABLE IF EXISTS `notification`;
CREATE TABLE `notification` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `sender_id` bigint NULL DEFAULT NULL COMMENT '发送者ID（管理员），NULL表示系统自动发送',
  `receiver_id` bigint NOT NULL COMMENT '接收者ID（用户或管理员）',
  `type` varchar(20) NOT NULL COMMENT '通知类型：REJECT-驳回通知，APPROVE-通过通知，SYSTEM-系统通知，REVIEW-人工复核通知，MAIL-管理员邮件',
  `title` varchar(200) NOT NULL COMMENT '通知标题',
  `content` text NULL COMMENT '通知内容',
  `is_read` tinyint NULL DEFAULT 0 COMMENT '是否已读：1-已读，0-未读',
  `related_type` varchar(20) NULL DEFAULT NULL COMMENT '关联类型：CHECKIN-打卡记录，REVIEW-审核记录',
  `related_id` bigint NULL DEFAULT NULL COMMENT '关联ID（如打卡记录ID、审核记录ID）',
  `extra_data` text NULL COMMENT '额外数据（JSON格式，存储关联信息）',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `read_at` datetime NULL DEFAULT NULL COMMENT '阅读时间',
  PRIMARY KEY (`id`),
  INDEX `idx_receiver_id`(`receiver_id`),
  INDEX `idx_sender_id`(`sender_id`),
  INDEX `idx_is_read`(`is_read`),
  INDEX `idx_type`(`type`),
  INDEX `idx_created_at`(`created_at`),
  INDEX `idx_receiver_id_is_read`(`receiver_id`, `is_read`),
  CONSTRAINT `fk_notification_receiver_id` FOREIGN KEY (`receiver_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notification_sender_id` FOREIGN KEY (`sender_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='通知消息表';

-- 7. 称号表
DROP TABLE IF EXISTS `title`;
CREATE TABLE `title` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` varchar(50) NOT NULL COMMENT '称号名称',
  `icon` varchar(10) NULL DEFAULT NULL COMMENT '图标（emoji）',
  `base_cost` int NULL DEFAULT 100 COMMENT '基础解锁费用',
  `max_level` int NULL DEFAULT 5 COMMENT '最大等级',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_name`(`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='称号表';

-- 8. 用户称号关联表
DROP TABLE IF EXISTS `user_title`;
CREATE TABLE `user_title` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `title_id` bigint NOT NULL COMMENT '称号ID',
  `level` int NULL DEFAULT 0 COMMENT '等级：0-未解锁，1-5为等级',
  `is_equipped` tinyint NULL DEFAULT 0 COMMENT '是否佩戴：1-是，0-否',
  `is_displayed` tinyint NULL DEFAULT 0 COMMENT '是否在排行榜展示：1-是，0-否',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uk_user_title`(`user_id`, `title_id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_title_id`(`title_id`),
  INDEX `idx_is_displayed`(`is_displayed`),
  CONSTRAINT `user_title_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_title_ibfk_2` FOREIGN KEY (`title_id`) REFERENCES `title` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户称号关联表';

-- 9. 勋章表
DROP TABLE IF EXISTS `badge`;
CREATE TABLE `badge` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `name` varchar(50) NOT NULL COMMENT '勋章名称',
  `icon` varchar(10) NULL DEFAULT NULL COMMENT '图标（emoji）',
  `type` varchar(20) NOT NULL COMMENT '类型：plate-光盘系列，walk-健步系列，ride-骑行系列，general-综合成就',
  `target` int NOT NULL COMMENT '解锁目标值',
  `stat_key` varchar(50) NOT NULL COMMENT '统计字段名（对应user表的字段）',
  `description` varchar(200) NULL DEFAULT NULL COMMENT '描述',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_type`(`type`),
  INDEX `idx_stat_key`(`stat_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='勋章表';

-- 10. 用户勋章关联表
DROP TABLE IF EXISTS `user_badge`;
CREATE TABLE `user_badge` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `badge_id` bigint NOT NULL COMMENT '勋章ID',
  `is_equipped` tinyint NULL DEFAULT 0 COMMENT '是否佩戴：1-是，0-否',
  `is_displayed` tinyint NULL DEFAULT 0 COMMENT '是否在排行榜展示：1-是，0-否',
  `unlock_time` datetime NULL DEFAULT NULL COMMENT '解锁时间',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uk_user_badge`(`user_id`, `badge_id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_badge_id`(`badge_id`),
  INDEX `idx_is_displayed`(`is_displayed`),
  CONSTRAINT `user_badge_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_badge_ibfk_2` FOREIGN KEY (`badge_id`) REFERENCES `badge` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户勋章关联表';

-- 11. 聊天记录表
DROP TABLE IF EXISTS `chat_record`;
CREATE TABLE `chat_record` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `role` varchar(20) NOT NULL COMMENT '角色：user-用户，ai-AI',
  `content` text NOT NULL COMMENT '消息内容',
  `source` varchar(50) NULL DEFAULT NULL COMMENT '来源：knowledge_base-知识库，llm_fallback-LLM回退，error-错误',
  `similarity` decimal(5, 4) NULL DEFAULT NULL COMMENT '相似度（知识库时存在）',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  INDEX `idx_user_id`(`user_id`),
  INDEX `idx_created_at`(`created_at`),
  CONSTRAINT `chat_record_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天记录表';

-- ============================================
-- 初始化数据
-- ============================================

-- 插入默认场景配置（包含 daily_limit, bonus_step, bonus_percentage 字段）
INSERT INTO `scene_config` (`scene_type`, `icon`, `title`, `tag`, `tag_type`, `reward_points`, `carbon_reduction`, `daily_limit`, `bonus_step`, `bonus_percentage`, `requirement_text`, `min_value`, `unit`, `keywords`, `exclude_keywords`) VALUES
('walk', '🏃', '低碳健步走', 'OCR 步数识别', 'primary', 10, 0.2000, 3, 1000.00, 10.00, '请上传微信运动或手环APP的今日步数截图，步数需超过 5000 步。', 5000.00, '步', '["步数", "步", "今日步数", "微信运动"]', '[]'),
('ride', '🚲', '绿色骑行', 'OCR 里程识别', 'primary', 15, 0.5000, 3, 1.00, 10.00, '请上传共享单车行程结束截图，骑行距离需大于 1.5km。', 1.50, 'km', '["骑行", "公里", "km", "行程"]', '[]'),
('plate', '🍽️', '光盘行动', 'AI 识别', 'success', 8, 0.1000, 3, NULL, NULL, '请上传空盘照片，系统将通过AI识别进行验证。', NULL, '', '["光盘", "空盘", "吃完"]', '["剩菜", "浪费"]'),
('transit', '🚌', '公共交通', 'OCR 票据识别', 'primary', 12, 0.6000, 3, NULL, NULL, '请上传乘车扣费记录或电子车票，日期需为今日。', NULL, '', '["公交", "地铁", "乘车", "扣费"]', '[]');

-- 插入默认称号
INSERT INTO `title` (`name`, `icon`, `base_cost`, `max_level`) VALUES
('低碳萌新', '🌱', 100, 5),
('环保先锋', '🌿', 150, 5),
('减排达人', '♻️', 200, 5),
('绿色领主', '🌲', 250, 5),
('地球卫士', '🌍', 300, 5),
('碳中和大使', '⚡', 400, 5),
('自然之子', '🦋', 500, 5),
('盖亚传说', '👑', 800, 5);

-- 插入默认勋章
INSERT INTO `badge` (`name`, `icon`, `type`, `target`, `stat_key`, `description`) VALUES
('粒粒皆辛苦', '🍚', 'plate', 1, 'plate_checkins', '完成首次光盘打卡'),
('惜食如金', '🥗', 'plate', 10, 'plate_checkins', '累计光盘打卡10次'),
('光盘王者', '🍽️', 'plate', 50, 'plate_checkins', '累计光盘打卡50次'),
('净坛使者', '👑', 'plate', 100, 'plate_checkins', '累计光盘打卡100次'),
('迈出第一步', '👣', 'walk', 1, 'walk_checkins', '完成首次健步走打卡'),
('日行千里', '🦶', 'walk', 10, 'walk_checkins', '累计健步走打卡10次'),
('健步如飞', '🏃', 'walk', 50, 'walk_checkins', '累计健步走打卡50次'),
('马拉松达人', '🏅', 'walk', 100, 'walk_checkins', '累计健步走打卡100次'),
('骑行初体验', '🚴', 'ride', 1, 'ride_checkins', '完成首次骑行打卡'),
('风驰电掣', '🚲', 'ride', 20, 'ride_checkins', '累计骑行打卡20次'),
('绿色骑士', '🏍️', 'ride', 50, 'ride_checkins', '累计骑行打卡50次'),
('初出茅庐', '🌟', 'general', 10, 'total_checkins', '累计打卡10次'),
('坚持不懈', '💪', 'general', 30, 'total_checkins', '累计打卡30次'),
('低碳达人', '🏆', 'general', 100, 'total_checkins', '累计打卡100次'),
('环保大师', '🎖️', 'general', 200, 'total_checkins', '累计打卡200次');

SET FOREIGN_KEY_CHECKS = 1;
