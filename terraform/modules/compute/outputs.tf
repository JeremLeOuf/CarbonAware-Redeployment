output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.myapp.id
}

output "instance_public_ip" {
  description = "Public IP of the EC2 instance"
  value       = aws_instance.myapp.public_ip
}