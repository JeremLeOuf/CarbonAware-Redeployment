import argparse
import subprocess
import os
import requests
import time
from dotenv import load_dotenv
from pathlib import Path
import logging
from datetime import datetime
import json

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
                "log_msg": msg}  # ✅ Changed "message" to "log_msg"

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
        print(
            f"❌ Error fetching data for {region_code}: {exc}", level="error")
        log_message(
            f"Error fetching data for {region_code}: {exc}", level="error")
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
    log_message(
        f"Updated Terraform variables: Region={region}, Deployment_ID={deployment_id}")


def run_terraform():
    """Run Terraform apply."""
    log_message(f"\n🔄 Running Terraform deployment in: {TERRAFORM_DIR}")
    subprocess.run(["terraform", "init"], cwd=TERRAFORM_DIR, check=True)
    subprocess.run(["terraform", "apply", "-auto-approve"],
                   cwd=TERRAFORM_DIR, check=True)
    print("✅ Terraform deployment complete!")
    log_message("Terraform deployment complete!")


def get_terraform_output(output_var: str):
    """Retrieve a Terraform output variable."""
    cmd = ["terraform", "output", "-raw", output_var]
    result = subprocess.run(cmd, cwd=TERRAFORM_DIR,
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def get_old_instances(region: str):
    """Fetch running instances in the given AWS region tagged 'myapp-instance'."""
    try:
        cmd = [
            "aws", "ec2", "describe-instances",
            "--region", region,
            "--filters",
            "Name=tag:Name,Values=myapp-instance",
            "Name=instance-state-name,Values=running",
            "--query", "Reservations[*].Instances[*].[InstanceId]",
            "--output", "json"
        ]
        result = subprocess.run(cmd, capture_output=True,
                                text=True, check=True)
        instances = json.loads(result.stdout)
        return [inst for reservation in instances for inst in reservation]
    except subprocess.CalledProcessError as e:
        print(
            f"❌ Error fetching instances in {region}: {e}", level="error")
        log_message(
            f"Error fetching instances in {region}: {e}", level="error")
        return []


def terminate_instance(instance_id: str, region: str):
    """Terminate an EC2 instance."""
    print(f"🛑 Terminating old instance {instance_id} in {region}...")
    log_message(f"Terminating old instance {instance_id} in {region}...")
    subprocess.run(
        ["aws", "ec2", "terminate-instances",
            "--instance-ids", instance_id, "--region", region],
        check=True
    )
    print(f"✅ Successfully terminated {instance_id} in {region}")
    log_message(f"Successfully terminated {instance_id} in {region}")


def check_existing_deployments():
    """Check all AWS_REGIONS for running instances."""
    deployments = {}
    for region in AWS_REGIONS.keys():
        if instance_ids := get_old_instances(region):
            print(f"✅ Found running instance(s) in {region}: {instance_ids}")
            log_message(
                f"Found running instance(s) in {region}: {instance_ids}")
            deployments[region] = instance_ids
    return deployments


def deploy():
    """Main deployment logic."""
    best_region = find_best_region()
    deployments = check_existing_deployments()

    if not deployments:
        log_message(f"No existing deployment. Deploying in {best_region}...")
        print(f"No existing deployment. Deploying in {best_region}...")

    else:
        current_regions = list(deployments.keys())
        current_best_region = min(
            current_regions, key=lambda r: get_carbon_intensity(AWS_REGIONS[r])
        )

        if current_best_region == best_region:
            print(
                f"✅ No redeployment needed. Already in greenest region ({best_region}).")
            log_message(
                f"No redeployment needed. Already in greenest region ({best_region}).")
            return
        else:
            log_message(
                f"🌱 A lower carbon region is available: {best_region}. Redeploying...")

    update_tfvars(best_region)
    run_terraform()

    if instance_ip := get_terraform_output("instance_public_ip"):
        print(f"✅ New instance running at: http://{instance_ip}")
        log_message(f"New instance running at: http://{instance_ip}")

        # Terminate old instances
        for region, instance_ids in deployments.items():
            if region != best_region:
                for instance_id in instance_ids:
                    terminate_instance(instance_id, region)
    else:
        log_message(
            f"❌ Failed to retrieve new instance details in {best_region}", level="error")


# -------------------------------------------------------------------
# Run the Script
# -------------------------------------------------------------------
if __name__ == "__main__":
    deploy()
