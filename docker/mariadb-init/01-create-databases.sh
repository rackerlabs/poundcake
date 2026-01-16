#!/bin/bash
# MariaDB initialization script
# Creates databases and users for both PoundCake and StackStorm

set -e

echo "Initializing databases for PoundCake and StackStorm..."

# Create StackStorm database and user
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
    CREATE DATABASE IF NOT EXISTS stackstorm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    CREATE USER IF NOT EXISTS 'stackstorm'@'%' IDENTIFIED BY 'stackstorm';
    GRANT ALL PRIVILEGES ON stackstorm.* TO 'stackstorm'@'%';
    
    -- PoundCake database and user already created by MYSQL_DATABASE/MYSQL_USER env vars
    -- But ensure it exists
    CREATE DATABASE IF NOT EXISTS poundcake CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    GRANT ALL PRIVILEGES ON poundcake.* TO 'poundcake'@'%';
    
    FLUSH PRIVILEGES;
EOSQL

echo "Databases created successfully:"
echo "  - poundcake (user: poundcake)"
echo "  - stackstorm (user: stackstorm)"
