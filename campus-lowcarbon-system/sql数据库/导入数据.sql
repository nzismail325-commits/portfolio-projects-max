USE `campus_lowcarbon_db`;

-- 1. 清理环境
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE `chat_record`;
TRUNCATE TABLE `notification`;
TRUNCATE TABLE `checkin_location`;
TRUNCATE TABLE `review_record`;
TRUNCATE TABLE `checkin_record`;
TRUNCATE TABLE `user_badge`;
TRUNCATE TABLE `user_title`;
TRUNCATE TABLE `user`;
TRUNCATE TABLE `student_info`;
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================
-- 2. 创建并执行数据填充存储过程
-- ============================================

DELIMITER //
CREATE PROCEDURE PopulateFinalTestData()
BEGIN
    DECLARE i INT DEFAULT 1;
    DECLARE g_year INT;
    DECLARE c_name VARCHAR(100);
    DECLARE sid VARCHAR(20);
    DECLARE real_name VARCHAR(50);
    DECLARE class_val VARCHAR(50);
    
    -- 随机姓名素材（百家姓 + 常用名）
    DECLARE surnames VARCHAR(255) DEFAULT '王李张刘陈杨黄赵吴周徐孙马朱胡郭林何高梁郑罗宋谢唐韩曹许邓萧冯程叶魏苏潘葛范彭彭江';
    DECLARE names_male VARCHAR(255) DEFAULT '伟强磊洋杰涛军刚平辉勇超明健鹏飞龙博威才翰诚国栋宏远志平俊良亮兴';
    DECLARE names_female VARCHAR(255) DEFAULT '芳娜秀英敏静丽娟艳燕兰莉桂荣萍怡瑞青宁欣雅雨雪露珊锦梦莹';

    WHILE i <= 100 DO
        -- A. 确定学院 (4个学院，每个25人)
        IF i <= 25 THEN SET c_name = '计算机科学与工程学院';
        ELSEIF i <= 50 THEN SET c_name = '经济管理学院';
        ELSEIF i <= 75 THEN SET c_name = '环境与能源学院';
        ELSE SET c_name = '外国语学院';
        END IF;
        
        -- B. 确定年级 (每个学院内部，学生会被平摊到 2021-2024 四个年级)
        SET g_year = 2021 + ((i - 1) % 4);
        
        -- C. 生成学号 (年级 + 4位序号，如 20210001)
        SET sid = CONCAT(CAST(g_year AS CHAR), LPAD(CAST(CEIL(i/4) AS CHAR), 4, '0'));
        
        -- D. 随机生成真实姓名
        SET real_name = CONCAT(
            SUBSTRING(surnames, FLOOR(1 + RAND() * 40), 1),
            CASE WHEN RAND() > 0.5 
                 THEN SUBSTRING(names_male, FLOOR(1 + RAND() * 30), 1)
                 ELSE SUBSTRING(names_female, FLOOR(1 + RAND() * 30), 1)
            END,
            CASE WHEN RAND() > 0.7 
                 THEN SUBSTRING(names_male, FLOOR(1 + RAND() * 30), 1)
                 ELSE '' 
            END
        );
        
        -- E. 生成班级
        SET class_val = CONCAT(CAST(g_year AS CHAR), '级', ((i-1) % 3) + 1, '班');

        INSERT INTO `student_info` (`student_id`, `name`, `college`, `class_name`, `status`)
        VALUES (sid, real_name, c_name, class_val, 1);
        
        SET i = i + 1;
    END WHILE;
END //
DELIMITER ;

CALL PopulateFinalTestData();
DROP PROCEDURE IF EXISTS PopulateFinalTestData;

-- ============================================
-- 3. 插入 1 个管理员账号
-- ============================================
INSERT INTO `user` (`student_id`, `username`, `password`, `role`, `nickname`, `status`)
VALUES ('admin', '系统管理员', '123456', 'admin', '系统管理员', 1);

-- ============================================
-- 4. 自动注册 50 名学生 (2021级与2022级)
-- 支付密码 (payment_password) 保持为空 (NULL)
-- ============================================
INSERT INTO `user` (
    `student_id`, 
    `username`, 
    `password`, 
    `role`, 
    `nickname`, 
    `points`, 
    `total_checkins`, 
    `risk_level`, 
    `status`,
    `payment_password` -- 此处保持为 NULL
)
SELECT 
    `student_id`, 
    `name`, 
    '123456', 
    'student', 
    `name`, 
    FLOOR(RAND() * 500), 
    FLOOR(RAND() * 30),  
    'SAFE',
    1,
    NULL -- 明确设置为 NULL
FROM `student_info`
WHERE `student_id` LIKE '2021%' OR `student_id` LIKE '2022%';

-- ============================================
-- 5. 最终验证
-- ============================================
DELIMITER //
CREATE PROCEDURE PopulateRichCheckinData()
BEGIN
    DECLARE profile_index INT DEFAULT 1;
    DECLARE target_student_id VARCHAR(20);
    DECLARE target_user_id BIGINT;
    DECLARE profile_days INT;
    DECLARE profile_nickname VARCHAR(50);
    DECLARE profile_signature VARCHAR(200);
    DECLARE profile_prefix VARCHAR(30);
    DECLARE day_offset INT;
    DECLARE slot_index INT;
    DECLARE slot_total INT;
    DECLARE scene_val VARCHAR(20);
    DECLARE points_val INT;
    DECLARE submit_val DATETIME;
    DECLARE verify_time_val DATETIME;
    DECLARE checkin_id_val BIGINT;
    DECLARE image_url_val VARCHAR(255);
    DECLARE verify_steps_val JSON;
    DECLARE active_cutoff INT;
    DECLARE pending_index INT DEFAULT 1;
    DECLARE pending_user_id BIGINT;
    DECLARE pending_scene VARCHAR(20);
    DECLARE pending_submit_val DATETIME;
    DECLARE pending_image_url VARCHAR(255);

    WHILE profile_index <= 50 DO
        SET target_user_id = NULL;
        SET target_student_id = CASE
            WHEN profile_index <= 25 THEN CONCAT('2021', LPAD(profile_index, 4, '0'))
            ELSE CONCAT('2022', LPAD(profile_index - 25, 4, '0'))
        END;
        SELECT `id` INTO target_user_id FROM `user` WHERE `student_id` = target_student_id LIMIT 1;

        SET profile_days = CASE profile_index WHEN 1 THEN 24 WHEN 2 THEN 60 WHEN 3 THEN 45 WHEN 4 THEN 75 WHEN 5 THEN 50 WHEN 6 THEN 36 ELSE 10 + (profile_index % 10) END;
        SET profile_nickname = CASE profile_index
            WHEN 1 THEN '稳步低碳者'
            WHEN 2 THEN '校园低碳先锋'
            WHEN 3 THEN '均衡行动派'
            WHEN 4 THEN '晨跑节能星'
            WHEN 5 THEN '通勤减碳达人'
            WHEN 6 THEN '光盘小卫士'
            ELSE CONCAT('低碳同学', LPAD(profile_index, 2, '0'))
        END;
        SET profile_signature = CASE profile_index
            WHEN 1 THEN '保持规律低碳打卡，数据适合展示个人趋势。'
            WHEN 2 THEN '长期参与低碳行动，覆盖多场景高频打卡。'
            WHEN 3 THEN '四类低碳场景均衡参与，适合展示场景占比。'
            WHEN 4 THEN '健步走参与突出，形成稳定运动减碳习惯。'
            WHEN 5 THEN '公共交通和骑行通勤占比高，体现校园绿色出行。'
            WHEN 6 THEN '餐饮节约意识强，光盘行动记录集中稳定。'
            ELSE '持续参与校园低碳打卡，形成可统计的近期行为数据。'
        END;
        SET profile_prefix = CASE profile_index WHEN 1 THEN 'steady' WHEN 2 THEN 'leader' WHEN 3 THEN 'balanced' WHEN 4 THEN 'runner' WHEN 5 THEN 'commuter' WHEN 6 THEN 'plate' ELSE CONCAT('student', profile_index) END;

        IF target_user_id IS NOT NULL THEN
            UPDATE `user`
            SET `nickname` = profile_nickname, `signature` = profile_signature
            WHERE `id` = target_user_id;

            SET day_offset = profile_days - 1;
            WHILE day_offset >= 0 DO
                SET active_cutoff = CASE day_offset
                    WHEN 0 THEN 42
                    WHEN 1 THEN 36
                    WHEN 2 THEN 47
                    WHEN 3 THEN 31
                    WHEN 4 THEN 44
                    WHEN 5 THEN 29
                    WHEN 6 THEN 38
                    ELSE 50
                END;
                SET slot_total = CASE profile_index
                    WHEN 1 THEN CASE WHEN day_offset % 7 IN (0, 2, 5) THEN 2 ELSE 1 END
                    WHEN 2 THEN CASE WHEN day_offset <= 30 THEN 3 ELSE CASE WHEN day_offset % 3 = 0 THEN 2 ELSE 1 END END
                    WHEN 3 THEN CASE WHEN day_offset % 5 IN (0, 2) THEN 3 ELSE 2 END
                    WHEN 4 THEN CASE WHEN day_offset <= 20 OR day_offset % 4 = 0 THEN 3 ELSE 2 END
                    WHEN 5 THEN CASE WHEN day_offset % 7 IN (1, 2, 3, 4, 5) THEN 2 ELSE 1 END
                    WHEN 6 THEN CASE WHEN day_offset % 3 IN (0, 1) THEN 2 ELSE 1 END
                    ELSE CASE WHEN day_offset <= 6 THEN 2 ELSE 1 END
                END;
                IF profile_index > active_cutoff THEN
                    SET slot_total = 0;
                END IF;
                SET slot_index = 1;

                WHILE slot_index <= slot_total DO
                    SET scene_val = CASE profile_index
                        WHEN 1 THEN CASE (day_offset + slot_index) % 4 WHEN 0 THEN 'walk' WHEN 1 THEN 'plate' WHEN 2 THEN 'ride' ELSE 'transit' END
                        WHEN 2 THEN CASE (day_offset * 2 + slot_index) % 4 WHEN 0 THEN 'walk' WHEN 1 THEN 'ride' WHEN 2 THEN 'plate' ELSE 'transit' END
                        WHEN 3 THEN CASE (day_offset + slot_index * 2) % 4 WHEN 0 THEN 'walk' WHEN 1 THEN 'ride' WHEN 2 THEN 'plate' ELSE 'transit' END
                        WHEN 4 THEN CASE WHEN slot_index IN (1, 3) THEN 'walk' ELSE CASE day_offset % 3 WHEN 0 THEN 'ride' WHEN 1 THEN 'plate' ELSE 'transit' END END
                        WHEN 5 THEN CASE WHEN slot_index = 1 THEN 'transit' ELSE CASE day_offset % 4 WHEN 0 THEN 'ride' WHEN 1 THEN 'transit' WHEN 2 THEN 'plate' ELSE 'walk' END END
                        WHEN 6 THEN CASE WHEN slot_index = 1 THEN 'plate' ELSE CASE day_offset % 3 WHEN 0 THEN 'walk' WHEN 1 THEN 'ride' ELSE 'transit' END END
                        ELSE CASE (profile_index + day_offset + slot_index) % 4 WHEN 0 THEN 'walk' WHEN 1 THEN 'ride' WHEN 2 THEN 'plate' ELSE 'transit' END
                    END;
                    SET points_val = CASE scene_val
                        WHEN 'walk' THEN 11 + profile_index + (day_offset % 6)
                        WHEN 'ride' THEN 15 + profile_index + (day_offset % 7)
                        WHEN 'plate' THEN 8
                        ELSE 12
                    END;
                    SET submit_val = DATE_ADD(DATE_SUB(CURDATE(), INTERVAL day_offset DAY), INTERVAL (7 + slot_index * 4 + profile_index % 3) HOUR);
                    SET verify_time_val = DATE_ADD(submit_val, INTERVAL (1 + profile_index % 3) MINUTE);
                    SET image_url_val = CONCAT('/api/uploads/checkin/', scene_val, '/', CASE scene_val WHEN 'walk' THEN '低碳健步走.png' WHEN 'ride' THEN '骑行打卡图片.png' WHEN 'plate' THEN '光盘行动.png' ELSE '公共交通.png' END);
                    SET verify_steps_val = JSON_ARRAY(
                        JSON_OBJECT('step', 'hash', 'status', 'success', 'message', '图片未重复'),
                        JSON_OBJECT('step', 'ai', 'status', 'success', 'message', 'AI核验通过'),
                        JSON_OBJECT('step', 'value', 'status', 'success', 'value', CASE scene_val WHEN 'walk' THEN 6200 + profile_index * 500 + day_offset * 85 WHEN 'ride' THEN 2.0 + profile_index / 3 + day_offset / 20 ELSE NULL END)
                    );

                    INSERT INTO `checkin_record` (`user_id`, `scene_type`, `image_url`, `image_hash`, `status`, `reward_points`, `verify_reason`, `verify_steps`, `submit_time`, `verify_time`, `created_at`, `updated_at`)
                    VALUES (target_user_id, scene_val, image_url_val, MD5(CONCAT(profile_prefix, '-', target_user_id, '-', day_offset, '-', slot_index, '-', scene_val)), 'APPROVED', points_val, '演示数据：AI自动核验通过', verify_steps_val, submit_val, verify_time_val, submit_val, verify_time_val);

                    SET checkin_id_val = LAST_INSERT_ID();

                    INSERT INTO `review_record` (`checkin_id`, `user_id`, `scene_type`, `image_url`, `reason`, `reason_type`, `confidence`, `ai_reason`, `review_status`, `reviewer_id`, `review_comment`, `submit_time`, `review_time`, `created_at`, `updated_at`)
                    VALUES (checkin_id_val, target_user_id, scene_val, image_url_val, 'AI自动审核通过', 'info', 93 + profile_index, '演示数据自动通过', 'APPROVED', NULL, NULL, submit_val, verify_time_val, submit_val, verify_time_val);

                    IF scene_val IN ('walk', 'ride', 'transit') THEN
                        INSERT INTO `checkin_location` (`user_id`, `scene_type`, `start_latitude`, `start_longitude`, `start_address`, `start_time`, `end_latitude`, `end_longitude`, `end_address`, `end_time`, `distance`, `status`, `checkin_id`, `created_at`, `updated_at`)
                        VALUES (target_user_id, scene_val, 36.6700000 + profile_index / 1000 + day_offset / 10000, 117.0500000 + slot_index / 10000, CASE profile_index WHEN 4 THEN '操场' WHEN 5 THEN '校门公交站' ELSE '宿舍区' END, DATE_SUB(submit_val, INTERVAL (30 + profile_index * 3) MINUTE), 36.6840000 + profile_index / 1000 + day_offset / 10000, 117.0680000 + slot_index / 10000, CASE profile_index WHEN 4 THEN '体育馆' WHEN 5 THEN '教学楼站' ELSE '图书馆' END, submit_val, CASE scene_val WHEN 'walk' THEN 2100.00 + profile_index * 260 + day_offset * 35 WHEN 'ride' THEN 3400.00 + profile_index * 420 + day_offset * 55 ELSE 4800.00 + profile_index * 500 + day_offset * 70 END, 'COMPLETED', checkin_id_val, DATE_SUB(submit_val, INTERVAL (30 + profile_index * 3) MINUTE), submit_val);
                    END IF;

                    SET slot_index = slot_index + 1;
                END WHILE;

                SET day_offset = day_offset - 1;
            END WHILE;
        END IF;

        SET profile_index = profile_index + 1;
    END WHILE;

    WHILE pending_index <= 12 DO
        SET pending_user_id = NULL;
        SET target_student_id = CASE
            WHEN pending_index <= 6 THEN CONCAT('2021', LPAD(pending_index + 6, 4, '0'))
            ELSE CONCAT('2022', LPAD(pending_index, 4, '0'))
        END;
        SELECT `id` INTO pending_user_id FROM `user` WHERE `student_id` = target_student_id LIMIT 1;

        IF pending_user_id IS NOT NULL THEN
            SET pending_scene = CASE pending_index % 4 WHEN 0 THEN 'walk' WHEN 1 THEN 'ride' WHEN 2 THEN 'plate' ELSE 'transit' END;
            SET pending_submit_val = DATE_SUB(NOW(), INTERVAL (pending_index * 8 + 3) MINUTE);
            SET pending_image_url = CONCAT('/api/uploads/checkin/', pending_scene, '/', CASE pending_scene WHEN 'walk' THEN '低碳健步走.png' WHEN 'ride' THEN '骑行打卡图片.png' WHEN 'plate' THEN '光盘行动.png' ELSE '公共交通.png' END);

            INSERT INTO `checkin_record` (`user_id`, `scene_type`, `image_url`, `image_hash`, `status`, `reward_points`, `verify_reason`, `verify_steps`, `submit_time`, `verify_time`, `created_at`, `updated_at`)
            VALUES (pending_user_id, pending_scene, pending_image_url, MD5(CONCAT('pending-admin-', pending_index, '-', pending_user_id, '-', pending_scene)), 'PENDING', 0, '演示数据：AI置信度不足，转入人工复核', JSON_ARRAY(JSON_OBJECT('step', 'hash', 'status', 'success', 'message', '图片未重复'), JSON_OBJECT('step', 'ai', 'status', 'warning', 'message', 'AI置信度不足，需要人工复核')), pending_submit_val, NULL, pending_submit_val, pending_submit_val);

            SET checkin_id_val = LAST_INSERT_ID();

            INSERT INTO `review_record` (`checkin_id`, `user_id`, `scene_type`, `image_url`, `reason`, `reason_type`, `confidence`, `ai_reason`, `review_status`, `reviewer_id`, `review_comment`, `submit_time`, `review_time`, `created_at`, `updated_at`)
            VALUES (checkin_id_val, pending_user_id, pending_scene, pending_image_url, CASE pending_index % 3 WHEN 0 THEN '图片清晰度不足' WHEN 1 THEN '凭证信息需要人工确认' ELSE '定位与凭证需复核' END, CASE pending_index % 3 WHEN 0 THEN 'warning' WHEN 1 THEN 'info' ELSE 'danger' END, 58 + pending_index, '演示数据：用于管理员端最近活动与异常审核展示', 'PENDING', NULL, NULL, pending_submit_val, NULL, pending_submit_val, pending_submit_val);
        END IF;

        SET pending_index = pending_index + 1;
    END WHILE;

    UPDATE `user` u
    LEFT JOIN (
        SELECT `user_id`,
               SUM(`reward_points`) AS total_points,
               SUM(CASE WHEN `scene_type` = 'walk' THEN 1 ELSE 0 END) AS walk_count,
               SUM(CASE WHEN `scene_type` = 'plate' THEN 1 ELSE 0 END) AS plate_count,
               SUM(CASE WHEN `scene_type` = 'ride' THEN 1 ELSE 0 END) AS ride_count,
               SUM(CASE WHEN `scene_type` = 'transit' THEN 1 ELSE 0 END) AS transit_count,
               COUNT(*) AS total_count
        FROM `checkin_record`
        WHERE `status` = 'APPROVED'
        GROUP BY `user_id`
    ) s ON u.`id` = s.`user_id`
    SET u.`points` = COALESCE(s.`total_points`, 0),
        u.`walk_checkins` = COALESCE(s.`walk_count`, 0),
        u.`plate_checkins` = COALESCE(s.`plate_count`, 0),
        u.`ride_checkins` = COALESCE(s.`ride_count`, 0),
        u.`transit_checkins` = COALESCE(s.`transit_count`, 0),
        u.`total_checkins` = COALESCE(s.`total_count`, 0),
        u.`risk_level` = 'SAFE',
        u.`suspicious_count` = 0,
        u.`status` = 1
    WHERE u.`role` = 'student' AND u.`status` = 1;

    INSERT IGNORE INTO `user_badge` (`user_id`, `badge_id`, `is_equipped`, `is_displayed`, `unlock_time`)
    SELECT u.`id`, b.`id`, 0, 0, NOW()
    FROM `user` u
    JOIN `badge` b ON (
        (b.`stat_key` = 'walk_checkins' AND u.`walk_checkins` >= b.`target`) OR
        (b.`stat_key` = 'plate_checkins' AND u.`plate_checkins` >= b.`target`) OR
        (b.`stat_key` = 'ride_checkins' AND u.`ride_checkins` >= b.`target`) OR
        (b.`stat_key` = 'total_checkins' AND u.`total_checkins` >= b.`target`)
    )
    WHERE u.`role` = 'student' AND u.`status` = 1;
END //
DELIMITER ;

CALL PopulateRichCheckinData();
DROP PROCEDURE IF EXISTS PopulateRichCheckinData;

SELECT '测试数据初始化完成' AS Message;

SELECT student_id, username, nickname, points, walk_checkins, plate_checkins, ride_checkins, transit_checkins, total_checkins
FROM user
WHERE student_id IN ('20210001', '20220001', '20210002', '20220002', '20210003', '20220003');

-- 验证支付密码是否为空
SELECT student_id, username, nickname, payment_password 
FROM user 
WHERE role = 'student' 
LIMIT 5;

-- 验证专业与年级分布
SELECT college AS 学院, LEFT(student_id, 4) AS 年级, COUNT(*) AS 人数 
FROM student_info 
GROUP BY college, 年级;
