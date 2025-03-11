terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "networking" {
  source = "./modules/networking"
}

module "compute" {
  source            = "./modules/compute"
  aws_region        = var.aws_region
  amis             = var.amis
  security_group_id = module.networking.security_group_id
}
