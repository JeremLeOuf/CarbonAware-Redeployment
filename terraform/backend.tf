# backend.tf - Remote state configuration
terraform {
  backend "s3" {
    bucket         = "carbon-aware-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}