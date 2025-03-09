# Description: This script is used to deploy a new instance of an application in the AWS region with the lowest carbon intensity. It will terminate the old instance(s) if a new instance is successfully deployed. It will also update the DNS record in Route53 if the domain name and hosted zone ID are provided.
import contextlib
import subprocess
import os
import requests
import time
import json
from dotenv import load_dotenv
from pathlib import Path
import tempfile
import logging

# -------------------------------------------------------------------
# Load environment variables (from .env or system environment)
# -------------------------------------------------------------------
load_dotenv()
ELECTRICITY_MAPS_API = "https://api.electricitymap.org/v3/carbon-intensity/latest"
AUTH_TOKEN = os.getenv("ELECTRICITYMAPS_API_TOKEN", "")

# DNS updates for Route53:
HOSTED_ZONE_ID = os.getenv("HOSTED_ZONE_ID", "")
MYAPP_DOMAIN = os.getenv("DOMAIN_NAME", "")
DNS_TTL = 60

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
TERRAFORM_DIR = SCRIPT_DIR / "terraform"

# -------------------------------------------------------------------
# AWS Regions + Mapping to Electricity Map Zones
# -------------------------------------------------------------------
AWS_REGIONS = {
    "eu-west-1": "IE",  # Ireland
    "eu-west-2": "GB",  # London
    "eu-central-1": "DE"  # Frankfurt
}

# Friendly names for each region
REGION_FRIENDLY_NAMES = {
    "eu-west-1": "Ireland",
    "eu-west-2": "London",
    "eu-central-1": "Frankfurt"
}

# -------------------------------------------------------------------
# Configure logging
# -------------------------------------------------------------------

# Set the log file inside the project directory
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
# Functions for Carbon Intensity + Region Selection
# -------------------------------------------------------------------


def get_carbon_intensity(region_code: str) -> float:
    """
    Fetch the carbon intensity for a given zone (e.g., 'IE', 'GB', 'DE')
    from the Electricity Maps API.
    """
    headers = {"auth-token": AUTH_TOKEN}
    try:
        response = requests.get(
            f"{ELECTRICITY_MAPS_API}?zone={region_code}", headers=headers
        )
        response.raise_for_status()
        data = response.json()
        return data.get("carbonIntensity", float("inf"))
    except requests.exceptions.RequestException as exc:
        print(f"❌ Error fetching data for {region_code}: {exc}")
        return float("inf")


def find_best_region() -> str:
    """
    Determine which AWS region has the lowest carbon intensity
    by querying Electricity Maps for each region's zone.
    """
    carbon_data = {}
    for aws_region, map_zone in AWS_REGIONS.items():
        intensity = get_carbon_intensity(map_zone)
        friendly_name = REGION_FRIENDLY_NAMES.get(aws_region, aws_region)
        print(
            f"🌍 {aws_region} ({friendly_name}) Carbon Intensity: {intensity} gCO₂/kWh")
        carbon_data[aws_region] = intensity

    best_region = min(carbon_data, key=carbon_data.get)
    best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
    print(
        f"\n⚡ Recommended AWS Region (lowest carbon): {best_region} ({best_friendly})")
    return best_region

# -------------------------------------------------------------------
# Functions to Manage EC2 Instances + Terraform
# -------------------------------------------------------------------


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
            "--output", "text", "--no-cli-pager"
            # ✅ Use text output to reduce verbosity
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True)
        instances = result.stdout.split()
        return instances or []
    except subprocess.CalledProcessError as e:
        log_message(
            f"❌ Error fetching instances in {region}: {e}", level="error")
        return []


def check_existing_deployments():
    """
    Check all AWS_REGIONS for a running instance with the tag 'myapp-instance'.
    Returns a dict: { region: [instance_ids], ... }.
    """
    deployments = {}
    for region in AWS_REGIONS.keys():
        if instance_ids := get_old_instances(region):
            friendly_region = REGION_FRIENDLY_NAMES.get(region, region)
            print(
                f"✅ Found running instance(s) in {region} ({friendly_region}): {instance_ids}")
            deployments[region] = instance_ids
    return deployments


def terminate_instance(instance_id: str, region: str):
    """Terminate an EC2 instance in the specified AWS region with reduced output."""
    log_message(f"🛑 Terminating old instance {instance_id} in {region}...")

    cmd = [
        "aws", "ec2", "terminate-instances",
        "--instance-ids", instance_id,
        "--region", region,
        "--no-cli-pager",  # ✅ Suppresses interactive output
        "--output", "text"  # ✅ Makes it less verbose
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Successfully terminated {instance_id} in {region}")
        log_message("Successfully terminated {instance_id} in {region}")
    else:
        print(
            f"❌ Failed to terminate instance {instance_id} in {region}. Error: {result.stderr}")
        log_message(
            f"Failed to terminate instance {instance_id} in {region}. Error: {result.stderr}", level="error")


def update_tfvars(region: str):
    """
    Overwrite terraform.tfvars with the chosen region + a new deployment_id
    to force Terraform to create a fresh instance.
    """
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    deployment_id = int(time.time())

    with open(tfvars_path, "w") as f:
        f.write(f'aws_region = "{region}"\n')
        f.write(f'deployment_id = "{deployment_id}"\n')

    friendly_region = REGION_FRIENDLY_NAMES.get(region, region)
    print(
        f"✅ Updated Terraform variables: Region={region} ({friendly_region}), Deployment_ID={deployment_id}")
    log_message(
        f"Updated Terraform variables: Region={region} ({friendly_region}), Deployment_ID={deployment_id}")


def run_terraform():
    """Run Terraform apply with reduced verbosity and log to file."""
    print(f"🔄 Running Terraform deployment in: {TERRAFORM_DIR}")
    log_message(f"🔄 Running Terraform deployment in: {TERRAFORM_DIR}")

    with open(LOG_FILE, "a") as log_file:
        subprocess.run(["terraform", "init", "-input=false", "-no-color"],
                       cwd=TERRAFORM_DIR, stdout=log_file, stderr=log_file)
        subprocess.run(["terraform", "apply", "-auto-approve", "-compact-warnings", "-no-color"],
                       cwd=TERRAFORM_DIR, stdout=log_file, stderr=log_file)

    log_message("Terraform deployment complete!")
    print("✅ Terraform deployment complete!")


def get_terraform_output(output_var: str):
    """
    Retrieve a Terraform output by name, returning None if retrieval fails.
    """
    cmd = ["terraform", "output", "-raw", output_var]
    result = subprocess.run(cmd, cwd=TERRAFORM_DIR,
                            capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip() or None
    print(
        f"❌ Failed to retrieve Terraform output '{output_var}': {result.stderr}")
    return None

# -------------------------------------------------------------------
# Health Check
# -------------------------------------------------------------------


def wait_for_http_ok(ip_address: str, port=80, max_attempts=20, interval=5) -> bool:
    """
    Poll http://<ip_address>:<port> until we get a 200 response or we exhaust max_attempts.
    """
    url = f"http://{ip_address}"
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                print(f"✅ HTTP check succeeded for {url}")
                return True
        except requests.exceptions.RequestException as e:
            logging.debug(f"HTTP request exception for {url}: {e}")

        print(
            f"⏳ Attempt {attempt}/{max_attempts}: waiting for HTTP 200 from {url}...")
        time.sleep(interval)

    print(f"❌ Gave up waiting for a successful HTTP response from {url}")
    log_message(
        f"Gave up waiting for a successful HTTP response from {url}", level="error")
    return False

# -------------------------------------------------------------------
# DNS Update via Route53
# -------------------------------------------------------------------


def update_dns_record(new_ip: str, domain: str, zone_id: str, ttl: int = 60):
    """Update a Route53 A record (myapp.example.com) to point to 'new_ip'."""
    log_message(f"🔄 Updating DNS record {domain} → {new_ip}")

    change_batch = {
        "Comment": "Update A record to new instance IP",
        "Changes": [
            {
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": domain,
                    "Type": "A",
                    "TTL": ttl,
                    "ResourceRecords": [{"Value": new_ip}]
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile("w", delete=False) as tf:
        json.dump(change_batch, tf)
        temp_path = tf.name

    cmd = [
        "aws", "route53", "change-resource-record-sets",
        "--hosted-zone-id", zone_id,
        "--change-batch", f"file://{temp_path}",
        "--output", "text", "--no-cli-pager"  # ✅ Suppress output
    ]
    ret = subprocess.run(cmd, capture_output=True, text=True)

    if ret.returncode == 0:
        print(f"✅ Successfully updated DNS record {domain} to {new_ip}")
        log_message(f"Successfully updated DNS record {domain} to {new_ip}")
    else:
        print(f"❌ Failed to update DNS record {domain}", level="error")
        log_message(f"Failed to update DNS record {domain}", level="error")


# -------------------------------------------------------------------
# Main Deployment Logic
# -------------------------------------------------------------------


def deploy():
    """
    1. Find the best region (lowest carbon).
    2. If no instance is running, deploy there. Otherwise, compare with current region(s).
    3. If a better region is found, deploy new instance, wait for healthy, optionally update DNS,
       then terminate old instance(s).
    """
    best_region = find_best_region()
    best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
    deployments = check_existing_deployments()

    log_message(
        f"Starting redeployment process to {best_region}", region=best_region)
    print(
        f"Starting redeployment process to {best_region}")

    # CASE 1: No existing deployment
    if not deployments:
        print("\nℹ️  No instance deployed yet.")
        update_tfvars(best_region)
        run_terraform()

        if instance_ip := get_terraform_output("instance_public_ip"):
            print(
                f"⏳ Checking HTTP availability on the new instance: {instance_ip}")
            if wait_for_http_ok(instance_ip, 80):
                print(
                    f"✅ Deployment complete! New instance at: http://{instance_ip}")
                if MYAPP_DOMAIN and HOSTED_ZONE_ID:
                    update_dns_record(instance_ip, MYAPP_DOMAIN,
                                      HOSTED_ZONE_ID, DNS_TTL)  # ✅ Fix here
                    print(f"⏳ Waiting {DNS_TTL}s for DNS to propagate...")
                    time.sleep(DNS_TTL)
                    print("⏳ DNS should be propagated!")
            else:
                print(
                    "❌ The new instance is not responding on HTTP. Please investigate.")
        else:
            print("❌ Failed to retrieve instance details. Check Terraform outputs.")
        return

    # CASE 2: At least one instance is already deployed
    current_regions = list(deployments.keys())
    current_best_region = min(
        current_regions, key=lambda r: get_carbon_intensity(AWS_REGIONS[r])
    )
    current_best_friendly = REGION_FRIENDLY_NAMES.get(
        current_best_region, current_best_region)
    print(
        f"\nℹ️  Current region with the lowest intensity among deployed: {current_best_region} ({current_best_friendly})")

    if current_best_region != best_region:
        print(f"🌱 A lower carbon region is available: {best_region} ({best_friendly}) "
              f"(Currently: {current_best_region} ({current_best_friendly}))")

        update_tfvars(best_region)
        run_terraform()

        if instance_ip := get_terraform_output("instance_public_ip"):
            print(
                f"⏳ Checking HTTP availability on the new instance: {instance_ip}")
            if wait_for_http_ok(instance_ip, 80):
                print(
                    f"✅ Redeployment complete! New instance at: http://{instance_ip}")
                if MYAPP_DOMAIN and HOSTED_ZONE_ID:
                    update_dns_record(instance_ip, MYAPP_DOMAIN,
                                      HOSTED_ZONE_ID, DNS_TTL)  # ✅ Fix here
                # Terminate old instance(s)
                for region, instance_ids in deployments.items():
                    if region != best_region:
                        for instance_id in instance_ids:
                            terminate_instance(instance_id, region)
            else:
                print(
                    "❌ The new instance is not responding on HTTP. Aborting old-instance termination.")
        else:
            print("✅ No change needed - you're already in the greenest region.")


if __name__ == "__main__":
    deploy()
