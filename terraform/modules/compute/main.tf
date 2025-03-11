resource "aws_instance" "myapp" {
  ami           = var.amis[var.aws_region]
  instance_type = "t2.micro"
  vpc_security_group_ids = [var.security_group_id]  
  user_data = file("${path.root}/scripts/userdata.sh")

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "myapp-instance"
  }
}
