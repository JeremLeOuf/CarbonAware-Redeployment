terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

resource "random_id" "sg_suffix" {
  byte_length = 2
}

resource "aws_security_group" "myapp_sg" {
  name        = "myapp_sg_${random_id.sg_suffix.hex}"
  description = "Allow HTTP inbound traffic"
  vpc_id      = data.aws_vpc.default.id

  lifecycle {
    create_before_destroy = true
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "myapp" {
  ami           = var.amis[var.aws_region]
  instance_type = "t2.micro"

  vpc_security_group_ids = [aws_security_group.myapp_sg.id]

  tags = {
    Name = "myapp-instance"
  }

  user_data = <<-EOF
        #!/bin/bash
        apt-get update -y
        apt-get install -y docker.io
        systemctl enable docker
        systemctl start docker
        docker pull jeremleouf/myapp:latest
        docker run -d --restart unless-stopped -p 80:8080 --name myapp-container jeremleouf/myapp:latest
  EOF
}