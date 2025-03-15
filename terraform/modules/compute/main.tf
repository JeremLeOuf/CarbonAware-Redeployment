resource "aws_instance" "myapp" {
  ami           = var.amis[var.aws_region]
  instance_type = "t2.micro" 
	# Can be changed to a larger instance type if needed
  vpc_security_group_ids = [var.security_group_id]  
  user_data = file("${path.root}/scripts/userdata.sh") 
	# References the userdata script that will be executed on the instance on startup
 
  lifecycle {
    create_before_destroy = true 
	# Ensures that the instance is created before the old one is destroyed
  }
 
  tags = {
    Name = "myapp-instance"
  }
}
