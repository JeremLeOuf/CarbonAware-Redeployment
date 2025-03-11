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
ELECTRICITY_MAPS_API_TOKEN = "https://api.electricitymap.org/v3/carbon-intensity/latest"
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
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)  # Create the logs dir if missing

# -------------------------------------------------------------------
# AWS Regions + Mapping to Electricity Map Zones
# -------------------------------------------------------------------
AWS_REGIONS = {
    "eu-west-1": "IE",    # Ireland
    "eu-west-2": "GB",    # London
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
LOG_FILE = str(Path(__file__).parent / "logs/redeploy.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [Region: %(region)s] - %(log_msg)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


def log_message(msg, region=None, level="info"):
    """Log messages with timestamp and AWS region."""
    if region is None:
        raise ValueError(f"Missing region for log message: {msg}")

    log_data = {"region": region, "log_msg": msg}

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
            f"{ELECTRICITY_MAPS_API_TOKEN}?zone={region_code}", headers=headers
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
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True)
        instances = result.stdout.split()
        return instances or []
    except subprocess.CalledProcessError as e:
        log_message(
            f"Error fetching instances in {region}: {e}",
            region=region,
            level="error"
        )
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
    log_message(
        f"Terminating old instance {instance_id} in {region}...", region=region)

    cmd = [
        "aws", "ec2", "terminate-instances",
        "--instance-ids", instance_id,
        "--region", region,
        "--no-cli-pager",
        "--output", "text"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"⏳ Started termination of {instance_id} in {region}.")
        log_message(
            f"Started termination of {instance_id} in {region}.\n",
            region=region
        )
    else:
        print(
            f"❌ Failed to terminate instance {instance_id} in {region}. Error: {result.stderr}")
        log_message(
            f"Failed to terminate instance {instance_id} in {region}. Error: {result.stderr}",
            region=region,
            level="error"
        )


def find_old_sgs(region: str):
    """
    Return a list of SG IDs matching 'myapp_sg_' in the given region.
    """
    try:
        cmd = [
            "aws", "ec2", "describe-security-groups",
            "--region", region,
            "--filters", "Name=group-name,Values=myapp_sg_*",
            "--query", "SecurityGroups[].GroupId",
            "--output", "json", "--no-cli-pager"
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)  # list of SG IDs
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to find old security groups in {region}. Error: {e}")
        return []


def remove_security_groups(region: str):
    """
    Find and delete old 'myapp_sg_<suffix>' groups in the specified region.
    """
    sg_ids = find_old_sgs(region)
    for sg_id in sg_ids:
        cmd = [
            "aws", "ec2", "delete-security-group",
            "--group-id", sg_id,
            "--region", region,
            "--no-cli-pager",
            "--output", "text"
        ]
        print(f"🛑 Deleting SG {sg_id} in region {region}...")
        ret = subprocess.run(cmd, capture_output=True, text=True)
        if ret.returncode == 0:
            print(f"✅ Deleted security group {sg_id} in {region}.\n")


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
        f"\n✅ Updated Terraform variables: Region={region}, Deployment_ID={deployment_id}")
    log_message(
        f"Updated Terraform variables: Region={region} ({friendly_region}), Deployment_ID={deployment_id}\n",
        region=region
    )


def run_terraform(deploy_region):
    friendly_region = REGION_FRIENDLY_NAMES.get(deploy_region, deploy_region)
    print(
        f"\n🔄 Running Terraform deployment in {deploy_region} ({friendly_region})...")
    log_message(
        f"🔄 Running Terraform deployment in {deploy_region}...", region=deploy_region)

    remove_security_groups(deploy_region)

    log_file_path = LOGS_DIR / "terraform.log"
    with open(log_file_path, "a") as log_file:
        subprocess.run(
            ["terraform", "init", "-no-color"],
            cwd=TERRAFORM_DIR, stdout=log_file
        )
        subprocess.run(
            ["terraform", "apply", "-auto-approve",
             "-no-color"],
            cwd=TERRAFORM_DIR, stdout=log_file
        )

    log_message("Terraform deployment complete!", region=deploy_region)
    print("✅ Terraform deployment complete!\n")


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
    Poll http://<ip_address> until we get a 200 response or we exhaust max_attempts.
    """
    url = f"http://{ip_address}"
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                print(f"✅ HTTP check succeeded for {url} !\n")
                return True
        except requests.exceptions.RequestException as e:
            logging.debug(f"HTTP request exception for {url}: {e}")

        print(
            f"⏳ Attempt {attempt}/{max_attempts}: waiting for HTTP 200 from {url}...")
        time.sleep(interval)

    print(f"❌ Gave up waiting for a successful HTTP response from {url}")
    log_message(
        f"Gave up waiting for a successful HTTP response from {url}",
        region="N/A",
        level="error"
    )
    return False

# -------------------------------------------------------------------
# DNS Update via Route53
# -------------------------------------------------------------------


def update_dns_record(new_ip: str, domain: str, zone_id: str, ttl: int = 60, region="N/A"):
    """
    Update a Route53 A record (myapp.example.com) to point to 'new_ip'.
    """
    log_message(f"Updating DNS record {domain} → {new_ip}", region=region)

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
        "--output", "text", "--no-cli-pager"
    ]
    ret = subprocess.run(cmd, capture_output=True, text=True)

    if ret.returncode != 0:
        print(ret.stderr)
        print(f"❌ Failed to update DNS record {domain}.")
        log_message(
            f"Failed to update DNS record {domain}.", region=region, level="error")

# -------------------------------------------------------------------
# Main Deployment Logic
# -------------------------------------------------------------------


def deploy():
    """
    Automates instance deployment based on carbon intensity,
    but allows the user to override the automatically chosen region.
    """

    # 1. Auto-find recommended region
    auto_region = find_best_region()

    # 2. Prompt user to override or use the auto-chosen region
    user_region_input = input(
        f"\nEnter a region to override the recommendation ({', '.join(AWS_REGIONS.keys())}) or press Enter to accept '{auto_region}': "
    ).strip()

    if user_region_input in AWS_REGIONS.keys():
        chosen_region = user_region_input
        print(f"\nUsing user-specified region: {chosen_region}")
    else:
        chosen_region = auto_region
        print(f"\nUsing recommended region: {chosen_region}")

    friendly = REGION_FRIENDLY_NAMES.get(chosen_region, chosen_region)

    # Check existing deployments
    deployments = check_existing_deployments()

    # If an instance is already running in chosen_region, do nothing
    if chosen_region in deployments:
        log_message(
            f"No redeployment needed, keeping current state in {chosen_region} ({friendly}).",
            region=chosen_region
        )
        print(
            f"✅ No redeployment needed, keeping current state in {chosen_region} ({friendly}).")
        return

    # CASE 1: No instances are currently running
    if not deployments:
        print("\nℹ️ No instance deployed yet. Starting fresh deployment...")

        update_tfvars(chosen_region)
        run_terraform(chosen_region)

        if instance_ip := get_terraform_output("instance_public_ip"):
            print(
                f"⏳ Checking HTTP availability on the new instance: {instance_ip}...")
            if wait_for_http_ok(instance_ip, 80):
                if MYAPP_DOMAIN and HOSTED_ZONE_ID:
                    update_dns_record(
                        instance_ip, MYAPP_DOMAIN, HOSTED_ZONE_ID, DNS_TTL, region=chosen_region)
                    print(
                        f"⏳ Updating DNS record {MYAPP_DOMAIN} → {instance_ip}. Waiting {DNS_TTL}s for DNS to propagate...")
                    time.sleep(DNS_TTL)
                    print(
                        f"✅ DNS record updated: {MYAPP_DOMAIN} → {instance_ip}\n ✅ Deployment complete! Application available at: http://{MYAPP_DOMAIN}.")
            else:
                print(
                    "❌ The new instance is not responding on HTTP. Please investigate.")
        else:
            print("❌ Failed to retrieve instance details. Check Terraform outputs.")
        return

    # CASE 2: Instances exist, but a lower-carbon region is requested
    current_best_region = min(
        deployments.keys(), key=lambda r: get_carbon_intensity(AWS_REGIONS[r]))
    current_best_friendly = REGION_FRIENDLY_NAMES.get(
        current_best_region, current_best_region)

    print(
        f"\nℹ️ Current region with the lowest intensity among the ones available: {current_best_region} ({current_best_friendly})")

    if current_best_region != chosen_region:
        print(
            f"🌱 A lower carbon region is available: {current_best_region} ({current_best_friendly}) !\n"
            f"\nℹ️ Currently deploying to: {chosen_region} ({friendly})."
        )

        update_tfvars(chosen_region)
        run_terraform(chosen_region)

        if instance_ip := get_terraform_output("instance_public_ip"):
            print(
                f"⏳ Checking HTTP availability on the new instance: {instance_ip}...")
            if wait_for_http_ok(instance_ip, 80):
                if MYAPP_DOMAIN and HOSTED_ZONE_ID:
                    update_dns_record(
                        instance_ip, MYAPP_DOMAIN, HOSTED_ZONE_ID, DNS_TTL, region=chosen_region)
                print(f"⏳ Waiting {DNS_TTL}s for DNS to propagate...")
                time.sleep(DNS_TTL)
                print(
                    f"\n✅ Redeployment complete! Application available at: http://{MYAPP_DOMAIN}.\n")
                # Terminate old instance(s)
                for reg, instance_ids in deployments.items():
                    if reg != chosen_region:
                        for inst_id in instance_ids:
                            terminate_instance(inst_id, reg)
                            remove_security_groups(reg)

            else:
                print(
                    "❌ The new instance is not responding on HTTP. Aborting old-instance termination.\n")
        else:
            print("✅ No change needed - you're already in the greenest region.")


if __name__ == "__main__":
    deploy()
