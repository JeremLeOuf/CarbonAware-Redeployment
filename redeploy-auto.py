import argparse
import subprocess
import os
import requests
import time
from dotenv import load_dotenv
from pathlib import Path
import logging
from datetime import datetime

# -------------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------------
load_dotenv()
ELECTRICITY_MAPS_API = "https://api.electricitymap.org/v3/carbon-intensity/latest"
AUTH_TOKEN = os.getenv("ELECTRICITYMAPS_API_TOKEN", "")

# AWS & Route53
HOSTED_ZONE_ID = os.getenv("HOSTED_ZONE_ID", "")
MYAPP_DOMAIN = os.getenv("DOMAIN_NAME", "")
DNS_TTL = int(os.getenv("DNS_TTL", "60"))

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
TERRAFORM_DIR = SCRIPT_DIR / "terraform"

# AWS Regions Mapping
AWS_REGIONS = {"eu-west-1": "IE", "eu-west-2": "GB", "eu-central-1": "DE"}
REGION_FRIENDLY_NAMES = {"eu-west-1": "Ireland",
                         "eu-west-2": "London", "eu-central-1": "Frankfurt"}


# -------------------------------------------------------------------
# Configure logging
# -------------------------------------------------------------------

LOG_FILE = str(Path(__file__).parent / "redeploy.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [Region: %(region)s] - %(log_msg)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


def log_message(msg, region="N/A", level="info"):
    """Log messages with timestamp and AWS region."""
    log_data = {"region": region,
                "log_msg": msg}

    if level == "error":
        logging.error(msg, extra=log_data)
    else:
        logging.info(msg, extra=log_data)


# -------------------------------------------------------------------
# Functions
# -------------------------------------------------------------------


def get_carbon_intensity(region_code: str) -> float:
    """Fetch the carbon intensity for a given AWS region using Electricity Maps API."""
    headers = {"auth-token": AUTH_TOKEN}
    try:
        response = requests.get(
            f"{ELECTRICITY_MAPS_API}?zone={region_code}", headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("carbonIntensity", float("inf"))
    except requests.exceptions.RequestException as exc:
        print(f"❌ Error fetching data for {region_code}: {exc}")
        return float("inf")


def find_best_region() -> str:
    """Determine which AWS region has the lowest carbon intensity."""
    carbon_data = {aws_region: get_carbon_intensity(
        map_zone) for aws_region, map_zone in AWS_REGIONS.items()}
    best_region = min(carbon_data, key=carbon_data.get)
    print(
        f"⚡ Recommended AWS Region (lowest carbon): {best_region} ({REGION_FRIENDLY_NAMES.get(best_region, best_region)})")
    return best_region


def update_tfvars(region: str):
    """Update terraform.tfvars with the chosen region."""
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    deployment_id = int(time.time())
    with open(tfvars_path, "w") as f:
        f.write(f'aws_region = "{region}"\n')
        f.write(f'deployment_id = "{deployment_id}"\n')
    print(
        f"✅ Updated Terraform variables: Region={region}, Deployment_ID={deployment_id}")


def run_terraform():
    """Run Terraform apply."""
    print(f"\n🔄 Running Terraform deployment in: {TERRAFORM_DIR}")
    subprocess.run(["terraform", "init"], cwd=TERRAFORM_DIR, check=True)
    subprocess.run(["terraform", "apply", "-auto-approve"],
                   cwd=TERRAFORM_DIR, check=True)
    print("✅ Terraform deployment complete!")


def get_terraform_output(output_var: str):
    """Retrieve a Terraform output variable."""
    cmd = ["terraform", "output", "-raw", output_var]
    result = subprocess.run(cmd, cwd=TERRAFORM_DIR,
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def deploy():
    """Main deployment logic."""
    best_region = find_best_region()
    best_region = "eu-west-1"  # For testing purposes
    log_message(
        f"Starting redeployment process to {best_region}...\n", region=best_region)

    update_tfvars(best_region)
    run_terraform()

    if instance_ip := get_terraform_output("instance_public_ip"):
        log_message(
            f"Deployment completed in {best_region}. Instance at: http://{instance_ip}\n", region=best_region)
    else:
        log_message(
            f"Failed to retrieve instance details in {best_region}\n", region=best_region, level="error")


# -------------------------------------------------------------------
# Run the Script
# -------------------------------------------------------------------
if __name__ == "__main__":
    deploy()
