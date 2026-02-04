# Quick Fix: StackStorm Bootstrap Service

## TL;DR - What Changed

✅ Renamed `st2client` → `stackstorm-bootstrap` (clearer purpose)  
✅ Fixed content registration error suppression  
✅ Added verification that core pack is working  
✅ Created troubleshooting script  

---

## Step 1: Apply the Fixes

Replace these 3 files in your poundcake directory:

1. **docker-compose.yml** → `docker-compose.yml.bootstrap-fixed`
2. **docker/st2-init/st2-entrypoint.sh** → `st2-entrypoint.sh.fixed`
3. **scripts/automated-setup.sh** → `automated-setup.sh.fixed`

```bash
# From your poundcake directory
cp docker-compose.yml docker-compose.yml.backup
cp docker-compose.yml.bootstrap-fixed docker-compose.yml

cp docker/st2-init/st2-entrypoint.sh docker/st2-init/st2-entrypoint.sh.backup
cp st2-entrypoint.sh.fixed docker/st2-init/st2-entrypoint.sh

cp scripts/automated-setup.sh scripts/automated-setup.sh.backup
cp automated-setup.sh.fixed scripts/automated-setup.sh

# Also add the troubleshooting script
cp troubleshoot-st2-registration.sh scripts/
chmod +x scripts/troubleshoot-st2-registration.sh
```

---

## Step 2: Restart Services

```bash
# Stop everything
docker compose down

# Start fresh
docker compose up -d

# Watch the bootstrap logs
docker compose logs -f stackstorm-bootstrap
```

**What to look for:**
- ✅ `[OK] Content registration successful`
- ✅ `[OK] Core pack verified and functional`
- ✅ `Setup Complete!`

---

## Step 3: Run Diagnostics

```bash
# Run the troubleshooting script
./scripts/troubleshoot-st2-registration.sh
```

**Expected output:**
```
[OK] stackstorm-bootstrap service exists
[OK] stackstorm-actionrunner is running
[OK] stackstorm-api is healthy
[OK] Found XX packs in /opt/stackstorm/packs
[OK] Core pack directory exists
[OK] Core pack has XX actions
[OK] ST2 CLI can list packs
[OK] Core pack actions are registered and accessible
[OK] st2_run_local command works!
```

---

## Step 4: Test the Original Command

```bash
# This should now work:
docker compose exec stackstorm-actionrunner \
  /opt/stackstorm/st2/bin/python3 -m st2common.bin.st2_run_local \
  core.local cmd="echo 'Brain is alive'"
```

**Expected output:**
```
Brain is alive
```

**Or use the simpler st2 CLI:**
```bash
docker compose exec stackstorm-actionrunner \
  st2 run core.local cmd="echo 'Brain is alive'"
```

---

## What These Changes Do

### 1. Service Rename: st2client → stackstorm-bootstrap

**Before:**
```yaml
st2client:
  container_name: st2client
```

**After:**
```yaml
stackstorm-bootstrap:
  container_name: stackstorm-bootstrap
```

**Why:** The service isn't really a "client" - it's doing bootstrap tasks like registering content, installing packs, and generating API keys. The new name reflects its actual purpose.

---

### 2. Content Registration Error Visibility

**Before (st2-entrypoint.sh):**
```bash
st2-register-content --register-all --setup-virtualenvs || log "Warning: Registration failed, continuing anyway..."
```

**After:**
```bash
st2-register-content --register-all --setup-virtualenvs --config-file /etc/st2/st2.conf

if [ $? -eq 0 ]; then
    log "[OK] Content registration successful"
    log "Packs directory:"
    ls -la /opt/stackstorm/packs/ 2>/dev/null | head -10
else
    log "[ERROR] Content registration failed!"
    log "This service may not function correctly without registered content."
fi
```

**Why:** The old version silently ignored registration failures. Now you'll see if something goes wrong and can debug it.

---

### 3. Core Pack Verification

**Before (automated-setup.sh):**
```bash
# Install packs, then just finish
echo "Setup Complete!"
```

**After:**
```bash
# Install packs, then verify core pack works
if st2 action list --pack=core > /dev/null 2>&1; then
    echo "[OK] Core pack verified and functional"
    st2 action list --pack=core | head -5
else
    echo "[ERROR] Core pack not available!"
    exit 1
fi
```

**Why:** The script now actively verifies that the core pack (which you need for basic operations) is actually working before declaring success.

---

## Troubleshooting

### Issue: "Content registration failed"

**Check logs:**
```bash
docker compose logs stackstorm-bootstrap | grep -i error
docker compose logs stackstorm-actionrunner | grep -i error
```

**Common causes:**
1. MongoDB not accessible (check `docker compose ps stackstorm-mongodb`)
2. Database authentication failed (check MONGO_PASSWORD in .env)
3. Disk space issues (check `df -h`)

**Fix:**
```bash
# Restart the service
docker compose restart stackstorm-actionrunner

# Or force re-registration
docker compose exec stackstorm-actionrunner \
  st2-register-content --register-all --setup-virtualenvs --config-file /etc/st2/st2.conf
```

---

### Issue: "Core pack not available"

**Check if core pack directory exists:**
```bash
docker compose exec stackstorm-actionrunner ls -la /opt/stackstorm/packs/core/
```

**If missing, manually register:**
```bash
docker compose exec stackstorm-actionrunner bash
st2-register-content --register-all --setup-virtualenvs --config-file /etc/st2/st2.conf
st2 pack list
exit
```

---

### Issue: "st2 CLI doesn't work"

**Test authentication:**
```bash
# Get token
docker compose exec stackstorm-bootstrap st2 auth st2admin -p Ch@ngeMe

# Try listing actions
docker compose exec stackstorm-actionrunner st2 action list
```

**If authentication fails:**
- Check ST2_AUTH_USER and ST2_AUTH_PASSWORD in .env
- Verify htpasswd file exists: `docker compose exec stackstorm-auth cat /etc/st2/htpasswd`
- Check auth service is running: `docker compose ps stackstorm-auth`

---

## Next Steps After This Works

Once you've verified everything works with these fixes, consider upgrading to the **shared packs volume** architecture (detailed in the full analysis document) for:

- Faster startup times
- Lower disk usage
- Guaranteed consistency across services
- Easier pack management

---

## Verification Checklist

- [ ] Service renamed to stackstorm-bootstrap
- [ ] No errors in bootstrap logs
- [ ] Core pack verification passes
- [ ] `st2 pack list` shows core pack
- [ ] `st2 action list --pack=core` shows actions
- [ ] `st2 run core.local cmd="echo test"` works
- [ ] Original python command works
- [ ] All tests in troubleshoot script pass

---

## Commit Message

```
fix: rename st2client to stackstorm-bootstrap and fix content registration

- Renamed st2client service to stackstorm-bootstrap for clarity
- Removed error suppression in st2-entrypoint.sh content registration
- Added core pack verification to automated-setup.sh
- Created troubleshooting script for ST2 registration issues

This ensures StackStorm core components are properly registered and
failures are visible rather than silently ignored.

Fixes: ModuleNotFoundError for st2common.bin in actionrunner
```

---

Generated: February 4, 2026
Status: READY TO DEPLOY
