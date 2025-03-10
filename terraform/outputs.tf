# terraform/outputs.tf

output "instance_public_ip" {
  description = "Public IP of the myapp instance"
  value       = aws_instance.myapp.public_ip
}

output "instance_id" {
  description = "ID of the myapp instance"
  value       = aws_instance.myapp.id
}

output "security_group_id" {
  description = "ID of the security group"
  value       = aws_security_group.myapp_sg.id
}
