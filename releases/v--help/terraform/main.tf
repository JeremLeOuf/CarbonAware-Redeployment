data "aws_vpc" "default" { # Fetches the default VPC in the region
  default = true
}

resource "random_id" "id" { # Generates a random ID to make the security group name unique
  byte_length = 4
}

resource "aws_security_group" "myapp_sg" {
  name        = "myapp_sg_${random_id.id.hex}" # Makes the security group name unique
  description = "Security group for myapp"
  vpc_id      = data.aws_vpc.default.id

  lifecycle {
    create_before_destroy = true # Ensures that the security group is created before the old one is destroyed
  }

  ingress {  # Allows inbound HTTP traffic from anywhere
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {  # Allows outbound traffic to anywhere
    description = "All traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

output "security_group_id" {
  description = "The ID of the SG created by the networking module"
  value       = aws_security_group.myapp_sg.id
}