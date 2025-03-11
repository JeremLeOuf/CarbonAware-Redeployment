#!/bin/bash
apt-get update -y
apt-get install -y docker.io
systemctl enable docker
systemctl start docker
docker pull jeremleouf/myapp:latest
docker run -d --restart unless-stopped -p 80:8080 --name myapp-container jeremleouf/myapp:latest