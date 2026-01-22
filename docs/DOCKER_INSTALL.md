# Docker Installation Guide for PoundCake API

> **Note**: This guide is for **local development only**. For production deployments,
> use the Helm chart. See [INSTALL.md](INSTALL.md) for Kubernetes installation instructions.

## Quick Install Script (Ubuntu/Debian)

For Ubuntu 20.04+, Debian 10+, just run this:

```bash
# One-command install (Ubuntu/Debian)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Verify installation
docker --version
docker-compose --version

# Test Docker
docker run hello-world
```

Then skip to [Running PoundCake API](#running-poundcake-api).

---

## Detailed Installation by OS

### Ubuntu / Debian

#### Step 1: Update System
```bash
sudo apt-get update
sudo apt-get upgrade -y
```

#### Step 2: Install Prerequisites
```bash
sudo apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release
```

#### Step 3: Add Docker's Official GPG Key
```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
```

#### Step 4: Set Up Repository
```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

#### Step 5: Install Docker
```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

#### Step 6: Verify Installation
```bash
sudo docker --version
sudo docker compose version
```

---

### CentOS / RHEL / Rocky Linux / AlmaLinux

#### Step 1: Update System
```bash
sudo yum update -y
```

#### Step 2: Remove Old Versions (if any)
```bash
sudo yum remove docker \
  docker-client \
  docker-client-latest \
  docker-common \
  docker-latest \
  docker-latest-logrotate \
  docker-logrotate \
  docker-engine
```

#### Step 3: Install Prerequisites
```bash
sudo yum install -y yum-utils
```

#### Step 4: Add Docker Repository
```bash
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
```

#### Step 5: Install Docker
```bash
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

#### Step 6: Start Docker
```bash
sudo systemctl start docker
sudo systemctl enable docker
```

#### Step 7: Verify Installation
```bash
sudo docker --version
sudo docker compose version
```

---

### Amazon Linux 2

```bash
# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify
docker --version
docker-compose --version
```

---

## Post-Installation Steps (All Distributions)

### Add Your User to Docker Group

This allows you to run Docker without `sudo`:

```bash
# Add current user to docker group
sudo usermod -aG docker $USER

# Apply the group change (or log out and back in)
newgrp docker

# Verify you can run docker without sudo
docker ps
```

### Enable Docker to Start on Boot

```bash
sudo systemctl enable docker
sudo systemctl enable containerd
```

---

## Verification Tests

### Test 1: Docker Version
```bash
docker --version
# Expected output: Docker version 24.0.x, build xxxxx
```

### Test 2: Docker Compose Version
```bash
docker compose version
# Expected output: Docker Compose version v2.x.x
```

### Test 3: Run Hello World
```bash
docker run hello-world
```

Expected output:
```
Hello from Docker!
This message shows that your installation appears to be working correctly.
```

### Test 4: Check Docker Service
```bash
sudo systemctl status docker
```

Should show "active (running)".

---

## Running PoundCake API

Once Docker is installed, you can run PoundCake API:

### Step 1: Extract the Archive
```bash
tar -xzf poundcake-api.tar.gz
cd poundcake-api
```

### Step 2: Run the Quickstart Script
```bash
./scripts/quickstart.sh
```

This will:
- Create `.env` file from template
- Start all Docker containers (MariaDB, Redis, API, Workers, Flower)
- Initialize the database
- Verify services are running

### Step 3: Verify Services

```bash
# Check all containers are running
docker ps

# Expected output: 5 containers running
# - poundcake-api-mariadb-1
# - poundcake-api-redis-1
# - poundcake-api-api-1
# - poundcake-api-worker-1 (x2)
# - poundcake-api-flower-1

# Test the API
curl http://localhost:8000/api/v1/health

# Expected output:
# {
# "status": "healthy",
# "version": "1.0.2",
# "database": "healthy",
# "redis": "healthy",
# "celery": "healthy (2 workers)",
# "timestamp": "2024-01-09T..."
# }
```

### Step 4: Access the Services

- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Flower Dashboard**: http://localhost:5555

---

## Troubleshooting

### Issue: "Cannot connect to the Docker daemon"

**Solution**: Make sure Docker service is running
```bash
sudo systemctl start docker
sudo systemctl status docker
```

### Issue: "permission denied while trying to connect"

**Solution**: Add your user to docker group and re-login
```bash
sudo usermod -aG docker $USER
# Then log out and log back in, or run:
newgrp docker
```

### Issue: "docker-compose: command not found"

**Solution**: Install Docker Compose plugin
```bash
# For Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker-compose-plugin

# For CentOS/RHEL
sudo yum install docker-compose-plugin

# Or install standalone version
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### Issue: Port 8000 already in use

**Solution**: Stop the conflicting service or change the port
```bash
# Find what's using port 8000
sudo lsof -i :8000

# Kill it (if safe to do so)
sudo kill -9 <PID>

# Or change PoundCake API port in docker-compose.yml
# Change "8000:8000" to "8001:8000"
```

### Issue: Containers start but immediately exit

**Solution**: Check container logs
```bash
docker-compose logs api
docker-compose logs postgres
docker-compose logs worker
```

---

## Firewall Configuration

If you're running on a cloud VM, you may need to open ports:

### AWS Security Group
- Port 8000 (API)
- Port 5555 (Flower)

### UFW (Ubuntu Firewall)
```bash
sudo ufw allow 8000/tcp
sudo ufw allow 5555/tcp
sudo ufw reload
```

### Firewalld (CentOS/RHEL)
```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --permanent --add-port=5555/tcp
sudo firewall-cmd --reload
```

---

## Resource Requirements

### Minimum Requirements
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 20 GB
- **OS**: Linux (Ubuntu 20.04+, CentOS 7+, etc.)

### Recommended for Production
- **CPU**: 4+ cores
- **RAM**: 8+ GB
- **Disk**: 50+ GB (with monitoring)
- **Network**: 1 Gbps

---

## Alternative: Docker Desktop (for Development)

### Windows with WSL2
1. Install WSL2: https://docs.microsoft.com/en-us/windows/wsl/install
2. Install Docker Desktop: https://www.docker.com/products/docker-desktop
3. Enable WSL2 backend in Docker Desktop settings
4. Run commands in WSL2 terminal

### macOS
1. Install Docker Desktop: https://www.docker.com/products/docker-desktop
2. Run Docker Desktop application
3. Run commands in Terminal

---

## Complete Installation Example (Ubuntu 22.04)

Here's a complete start-to-finish example:

```bash
# 1. Update system
sudo apt-get update && sudo apt-get upgrade -y

# 2. Install Docker using convenience script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 3. Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# 4. Verify installation
docker --version
docker compose version
docker run hello-world

# 5. Extract PoundCake API
tar -xzf poundcake-api.tar.gz
cd poundcake-api

# 6. Run quickstart
./scripts/quickstart.sh

# 7. Wait for services to start (30 seconds)
sleep 30

# 8. Test the API
curl http://localhost:8000/api/v1/health

# 9. Open in browser
# http://YOUR_VM_IP:8000/docs
```

---

## Next Steps After Installation

1. **Test with a sample webhook**:
 ```bash
 curl -X POST http://localhost:8000/api/v1/webhook \
   -H "Content-Type: application/json" \
   -d @tests/sample_webhook.json
 ```

2. **View logs**:
 ```bash
 docker-compose logs -f
 ```

3. **Check Flower dashboard**:
 - Open http://localhost:5555 in browser

4. **Explore API documentation**:
 - Open http://localhost:8000/docs in browser

5. **Configure Alertmanager**:
 - Edit `config/alertmanager.example.yml`
 - Point to your PoundCake API instance

---

## Useful Docker Commands

```bash
# View running containers
docker ps

# View all containers (including stopped)
docker ps -a

# View logs for all services
docker-compose logs -f

# View logs for specific service
docker-compose logs -f api

# Restart a service
docker-compose restart api

# Stop all services
docker-compose down

# Stop and remove volumes (fresh start)
docker-compose down -v

# Rebuild and start
docker-compose up -d --build

# Check resource usage
docker stats

# Enter a container shell
docker-compose exec api bash
docker-compose exec mariadb mysql -u poundcake -p poundcake
```

---

## Support

If you encounter issues:

1. Check Docker is running: `sudo systemctl status docker`
2. Check logs: `docker-compose logs -f`
3. Verify ports are available: `sudo lsof -i :8000`
4. Check firewall rules
5. Ensure sufficient resources (RAM, disk)

---

**You're now ready to run PoundCake API! **
