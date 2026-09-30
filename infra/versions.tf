terraform {
  required_version = ">= 1.5"

  required_providers {
    nebius = {
      source  = "nebius/nebius"
      version = ">= 0.6.8"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}

# Auth: the provider reads a user access token from NEBIUS_IAM_TOKEN
# (export NEBIUS_IAM_TOKEN=$(nebius iam get-access-token)). For service
# account key auth instead, add a `service_account` block, see:
# https://docs.nebius.com/terraform-provider/install
provider "nebius" {}
