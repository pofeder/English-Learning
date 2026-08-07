-- Run this file once in MySQL as root or another administrator.
-- Replace CHANGE_THIS_PASSWORD before executing.

CREATE DATABASE IF NOT EXISTS english_daily
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'english_app'@'%' IDENTIFIED BY 'lq673413.';
GRANT ALL PRIVILEGES ON english_daily.* TO 'english_app'@'%';
FLUSH PRIVILEGES;
