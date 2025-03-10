variable "aws_region" {
  type        = string
  description = "AWS region to deploy the instance"
  default = "eu-central-1"
}

variable "deployment_id" {
  type        = string
  description = "Unique deployment identifier (used to force new instance)"
  default = 0
}

variable "amis" {
  type = map(string)
  default = {
    "eu-west-1"     = "ami-0715d656023fe21b4" # Debian 12 for Ireland
    "eu-west-2"     = "ami-0efc5833b9d584374" # Debian 12 for London
    "eu-central-1"  = "ami-0584590e5f0e97daa" # Debian 12 for Frankfurt
  }
}