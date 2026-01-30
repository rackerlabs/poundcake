#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
set -e

echo "Creating PoundCake databases..."

mariadb -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
    -- PoundCake application database
    CREATE DATABASE IF NOT EXISTS poundcake CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    
    -- PoundCake user
    CREATE USER IF NOT EXISTS 'poundcake'@'%' IDENTIFIED BY 'poundcake';
    GRANT ALL PRIVILEGES ON poundcake.* TO 'poundcake'@'%';
    
    FLUSH PRIVILEGES;
EOSQL

echo "Database initialization complete!"
echo "Created databases:"
echo "  - poundcake (user: poundcake)"
echo ""
echo "Note: StackStorm uses MongoDB, not MariaDB"
