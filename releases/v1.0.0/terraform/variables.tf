variable "amis" { # Defined in the root variables.tf file
  type        = map(string)
  description = "Mapping of pinned AMIs by region"
}

variable "aws_region" { # Dynamically changed based on the lowest carbon intensity region
  type        = string
  description = "AWS region to deploy the instance in"
}

variable "security_group_id" { # Defined in the networking module
  type        = string
  description = "Security group ID to attach to the EC2 instance"
}