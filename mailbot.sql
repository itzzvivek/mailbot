--Users (identity only)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);


--Gmail accounts (one row per Gmail connection)
CREATE TABLE IF NOT EXISTS gmail_accounts (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    gmail_address TEXT NOT NULL,
    app_password TEXT NOT NULL,
    timezone TEXT DEFAULT 'Asia/Kolkata',
    last_uid BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (discord_id, gmail_address),
    FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_gmail_accounts_discord ON gmail_accounts(discord_id);
CREATE INDEX IF NOT EXISTS idx_gmail_accounts_email ON gmail_accounts(gmail_address);
CREATE INDEX IF NOT EXISTS idx_gmail_accounts_active ON gmail_accounts(is_active);


--User channels (which channel watches which Gmail account)
CREATE TABLE IF NOT EXISTS user_channels (
    id SERIAL PRIMARY KEY,
    gmail_account_id INTEGER NOT NULL,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    filters TEXT[] DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gmail_account_id, guild_id),
    FOREIGN KEY (gmail_account_id) REFERENCES gmail_accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_channels_account ON user_channels(gmail_account_id);
CREATE INDEX IF NOT EXISTS idx_user_channels_guild ON user_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_user_channels_active ON user_channels(is_active);


--Notification logs
CREATE TABLE IF NOT EXISTS notification_logs (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    gmail_account_id INTEGER,
    sender VARCHAR(255),
    subject VARCHAR(500),
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_discord_id ON notification_logs(discord_id);
CREATE INDEX IF NOT EXISTS idx_logs_sent_at ON notification_logs(sent_at);