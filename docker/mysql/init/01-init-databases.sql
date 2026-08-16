-- EcoGain 认证库初始化（docker-entrypoint-initdb.d 首次启动执行）
CREATE DATABASE IF NOT EXISTS ecogain_auth DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE ecogain_auth;

CREATE TABLE IF NOT EXISTS auth_users (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  username       VARCHAR(64)  NOT NULL,
  password_hash  VARCHAR(100) NOT NULL COMMENT 'bcrypt(cost=12)',
  display_name   VARCHAR(128) NOT NULL DEFAULT '',
  role           VARCHAR(16)  NOT NULL DEFAULT 'analyst' COMMENT 'analyst | admin',
  status         VARCHAR(16)  NOT NULL DEFAULT 'active',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_username (username),
  CONSTRAINT chk_au_role CHECK (role IN ('analyst','admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='认证中心用户';

CREATE TABLE IF NOT EXISTS auth_clients (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  client_id      VARCHAR(64)  NOT NULL,
  client_secret  VARCHAR(128) NOT NULL COMMENT '服务间共享密钥（环境变量注入，不进日志）',
  client_name    VARCHAR(128) NOT NULL,
  redirect_uri   VARCHAR(512) NOT NULL COMMENT '精确匹配校验',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_client_id (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OAuth2 客户端';

CREATE TABLE IF NOT EXISTS auth_codes (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code           VARCHAR(64)  NOT NULL,
  client_id      VARCHAR(64)  NOT NULL,
  user_id        BIGINT UNSIGNED NOT NULL,
  redirect_uri   VARCHAR(512) NOT NULL,
  expires_at     DATETIME(3)  NOT NULL COMMENT '5 分钟',
  consumed_at    DATETIME(3)  NULL,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_code (code),
  KEY idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OAuth2 授权码（一次性）';

-- 业务系统库（表结构由 backend Alembic 迁移创建）
CREATE DATABASE IF NOT EXISTS ecogain DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
