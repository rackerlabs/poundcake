# PoundCake Configuration Directory

## st2_api_key File

This file contains the StackStorm API key used by PoundCake to authenticate with StackStorm.

### How It Works

1. **Auto-generated:** The `st2client` container generates this on first run
2. **Location:** `/app/config/st2_api_key` (in containers)
3. **Source of truth:** This is the ONLY place the API reads the key from
4. **Format:** Base64-encoded string (80 characters)

### Important Notes

**The .env file ST2_API_KEY is NOT used!**

The `ST2_API_KEY` entry in `.env` is updated by st2client as a reference/backup, but:
- It's NOT passed to containers as an environment variable
- The API reads from THIS file (`st2_api_key`), not from .env
- You can safely ignore the .env entry

### Persistence Across Restarts

This directory is a bind mount, so files persist across:
- `docker compose restart`
- `docker compose down`
- `docker compose down -v` (!)

**This is why greenfield deployments need cleanup!**

### Fresh Deployment

For a true fresh start:

```bash
# Option 1: Use the cleanup script (recommended)
./scripts/clean-config.sh
docker compose down -v
docker compose up -d

# Option 2: Manual cleanup
rm -f config/st2_api_key
docker compose down -v
docker compose up -d
```

### Validation

The st2client now validates existing keys before skipping generation:

```
Found existing key → Test against StackStorm
  ├─ Valid → Keep and skip generation
  └─ Invalid → Delete and regenerate
```

This prevents issues when MongoDB is wiped but the key file persists.

### Security

**Do not commit this file to git!**

The `.gitignore` file excludes `config/st2_api_key` to prevent accidentally committing secrets.

### Troubleshooting

**Problem:** 401 Unauthorized errors from StackStorm

**Solution:**
```bash
# Check if key exists
cat config/st2_api_key

# If empty or missing, regenerate
rm -f config/st2_api_key
docker compose restart st2client
docker compose logs -f st2client
```

**Problem:** Old key from previous deployment

**Solution:**
```bash
./scripts/clean-config.sh
docker compose restart st2client
```

### File Structure

```
config/
├── README.md          (this file)
└── st2_api_key       (auto-generated, DO NOT COMMIT)
```
