#!/bin/bash
# This script installs Docker and deploys the latest myapp container from Docker Hub

# Update package lists and install Docker
apt-get update -y
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

# Ensure old container (if any) is stopped and removed
docker stop myapp-container || true
docker rm myapp-container || true

# Ensure we pull the latest version
docker pull jeremleouf/myapp:latest

# Run the container with automatic restart
docker run -d --restart unless-stopped -p 80:8080 --name myapp-container jeremleouf/myapp:latest
