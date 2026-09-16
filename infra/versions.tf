terraform {
  required_version = ">= 1.5"

  required_providers {
    nebius = {
      source  = "nebius/nebius"
      version = ">= 0.6.8"
    }
  }
}

# Auth: either set `token` (user access token) or the `service_account`
# attributes below via env vars. See:
# https://docs.nebius.com/terraform-provider/install
provider "nebius" {
  service_account = {
    private_key_file_env = "AUTHKEY_PRIVATE_PATH"
    public_key_id_env    = "AUTHKEY_PUBLIC_ID"
    account_id_env       = "SA_ID"
  }
}
