data "aws_vpc" "default" {
  default = true
}

resource "random_id" "id" {
  byte_length = 4
}

resource "aws_security_group" "myapp_sg" {
  name        = "myapp_sg_${random_id.id.hex}"
  description = "Security group for myapp"
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

output "security_group_id" {
  description = "The ID of the SG created by networking module"
  value       = aws_security_group.myapp_sg.id
}