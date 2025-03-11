output "security_group_id" {
  description = "The ID of the SG created by networking module"
  value       = aws_security_group.myapp_sg.id
}