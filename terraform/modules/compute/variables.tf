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