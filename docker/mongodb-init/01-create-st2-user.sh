#!/bin/bash
#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
# Create StackStorm database and user in MongoDB

mongosh --username admin --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin <<EOF
use st2;
db.createUser({
  user: "stackstorm",
  pwd: "stackstorm",
  roles: [
    { role: "dbOwner", db: "st2" }
  ]
});
print("StackStorm user created successfully");
EOF
