output "instance_id" {
  description = "EC2 instance ID from the compute module"
  value       = module.compute.instance_id
}

output "instance_public_ip" {
  description = "Public IP from the compute module"
  value       = module.compute.instance_public_ip
}


output "security_group_id" {
  description = "ID of the security group for myapp"
  value       = module.networking.security_group_id
}