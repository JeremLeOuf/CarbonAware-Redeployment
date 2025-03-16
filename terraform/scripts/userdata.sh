#!/bin/bash
# Update system and install Docker
apt-get update -y
apt-get install -y docker.io

# Enable and start Docker service
systemctl enable docker
systemctl start docker

# Define the Docker image name (modify as needed)
# DOCKER_IMAGE="fanvinga/docker-2048:latest" # 2048 game
DOCKER_IMAGE="dbafromthecold/pac-man:latest" # Pacman game
# DOCKER_IMAGE="jeremleouf/myapp:latest" # My weather app
# DOCKER_IMAGE="itzg/minecraft-server:latest" # Minecraft server
# DOCKER_IMAGE="supertuxkart/stk-server" # Supertuxkart server

# Define a generic container name
CONTAINER_NAME="app-container"

# Stop and remove any existing container
docker stop $CONTAINER_NAME || true
docker rm $CONTAINER_NAME || true

# Pull the latest image from Docker Hub
docker pull $DOCKER_IMAGE

# Run the container on port 80
docker run -d --restart unless-stopped -p 80:80 --name $CONTAINER_NAME $DOCKER_IMAGE
