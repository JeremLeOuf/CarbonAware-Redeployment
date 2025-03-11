variable "amis" {
  type        = map(string)
  description = "Mapping of pinned AMIs by region"
}

variable "aws_region" {
  type        = string
  description = "AWS region to deploy"
}

variable "security_group_id" {
  type        = string
  description = "Security group ID to attach to EC2"
}

resource "aws_instance" "myapp" {
  ami           = var.amis[var.aws_region]
  instance_type = "t2.micro"

  vpc_security_group_ids = [var.security_group_id]

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

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.myapp.id
}

output "instance_public_ip" {
  description = "Public IP of the EC2 instance"
  value       = aws_instance.myapp.public_ip
}
