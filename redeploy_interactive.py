"""
Interactive version of the carbon-aware deployment automation script.
Allows user input for deployment decisions while maintaining the same core functionality.
"""

# Standard library imports
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

# Third-party imports
import requests
from dotenv import load_dotenv

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
LOGS_DIR = SCRIPT_DIR / "logs"
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
            f"{ELECTRICITY_MAPS_API_TOKEN}?zone={region_code}",
            headers=headers,
            timeout=10
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
            f"🌍 '{aws_region}' ({friendly_name}) current carbon intensity: {intensity} gCO₂/kWh.")
        carbon_data[aws_region] = intensity

    best_region = min(carbon_data, key=carbon_data.get)
    best_intensity = carbon_data[best_region]
    best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
    print(
        f"\n⚡ Recommended AWS Region (lowest carbon intensity): '{best_region}' "
        f"({best_friendly}) - {best_intensity} gCO₂/kWh.")
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
    for region in AWS_REGIONS:
        if instance_ids := get_old_instances(region):
            friendly_region = REGION_FRIENDLY_NAMES.get(region, region)
            print(
                f"ℹ️ Found running instance(s) in '{region}' ({friendly_region}): {instance_ids}.")
            deployments[region] = instance_ids
    return deployments


def terminate_instance(instance_id: str, region: str):
    """
    Terminate an EC2 instance in the specified AWS region
    and block until the instance is fully terminated.
    """
    print(f"⏳ Terminating instance '{instance_id}' in '{region}'...")
    log_message(
        f"Started termination of instance '{instance_id}'...",
        region=region
    )

    # Step 1: Terminate the instance
    terminate_cmd = [
        "aws", "ec2", "terminate-instances",
        "--instance-ids", instance_id,
        "--region", region,
        "--no-cli-pager",
        "--output", "text"
    ]
    terminate_result = subprocess.run(
        terminate_cmd, capture_output=True, text=True, check=True
    )

    if terminate_result.returncode != 0:
        print(
            f"❌ Failed to terminate instance {instance_id} in {region}. "
            f"Error: {terminate_result.stderr}"
        )
        log_message(
            f"Failed to terminate instance '{instance_id}' in '{region}'. "
            f"Error: {terminate_result.stderr}",
            region=region,
            level="error"
        )
        return

    # Step 2: Wait until instance is fully terminated
    wait_cmd = [
        "aws", "ec2", "wait", "instance-terminated",
        "--instance-ids", instance_id,
        "--region", region
    ]
    wait_result = subprocess.run(
        wait_cmd, capture_output=True, text=True, check=True
    )
    if wait_result.returncode == 0:
        print(
            f"✅ Successfully terminated instance '{instance_id}' in '{region}'.\n")
        log_message(
            f"Successfully terminated instance '{instance_id}'.",
            region=region
        )
    else:
        print(
            f"❌ Wait for instance {instance_id} termination failed. "
            f"Error: {wait_result.stderr}"
        )
        log_message(
            f"Wait for instance '{instance_id}' termination failed. "
            f"Error: {wait_result.stderr}",
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
        print(f"⏳ Deleting SG '{sg_id}' in '{region}'...")
        log_message(f"Started deletion of SG '{sg_id}'...", region=region)
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True)
        if result.returncode == 0:
            print(f"✅ Successfully deleted SG '{sg_id}' in '{region}'.\n")
            log_message(
                f"Successfully deleted SG '{sg_id}'.", region=region)
        else:
            print(
                f"❌ Failed to delete SG '{sg_id}' in '{region}'. Error: {result.stderr}")


def update_tfvars(region: str):
    """
    Overwrite terraform.tfvars with the chosen region + a new deployment_id
    to force Terraform to create a fresh instance.
    """
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    deployment_id = int(time.time())

    with open(tfvars_path, "w", encoding="utf-8") as f:
        f.write(f'aws_region = "{region}"\n')
        f.write(f'deployment_id = "{deployment_id}"\n')

    log_message(
        f"Updated Terraform variables: 'Region={region}', 'Deployment_ID={deployment_id}'.",
        region="SYSTEM"
    )


def run_terraform(deploy_region: str):
    """Execute Terraform commands to deploy infrastructure."""
    friendly_region = REGION_FRIENDLY_NAMES.get(deploy_region, deploy_region)
    print(
        f"\n🔄 Running Terraform deployment in '{deploy_region}' "
        f"({friendly_region})...\n"
    )

    log_file_path = LOGS_DIR / "terraform.log"
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        subprocess.run(
            ["terraform", "init", "-no-color"],
            cwd=TERRAFORM_DIR,
            stdout=log_file,
            check=True
        )
        subprocess.run(
            ["terraform", "apply", "-auto-approve", "-no-color"],
            cwd=TERRAFORM_DIR,
            stdout=log_file,
            check=True
        )


def get_terraform_output(output_var: str):
    """
    Retrieve a Terraform output by name, returning None if retrieval fails.
    """
    cmd = ["terraform", "output", "-raw", output_var]
    result = subprocess.run(cmd, cwd=TERRAFORM_DIR,
                            capture_output=True, text=True, check=True)
    if result.returncode == 0:
        return result.stdout.strip() or None
    print(
        f"❌ Failed to retrieve Terraform output '{output_var}': {result.stderr}")
    return None

# -------------------------------------------------------------------
# Health Check
# -------------------------------------------------------------------


def wait_for_http_ok(ip_address: str, max_attempts=20, interval=5) -> bool:
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
            logging.debug("HTTP request exception for %s: %s", url, e)

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
    log_message(
        f"Updating DNS A record of '{domain}' to '{new_ip}'...",
        region=region
    )

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
    ret = subprocess.run(cmd, capture_output=True, text=True, check=True)

    if ret.returncode != 0:
        print(ret.stderr)
        print(f"❌ Failed to update DNS record {domain}.")
        log_message(
            f"Failed to update DNS record '{domain}'.", region=region, level="error")

# -------------------------------------------------------------------
# Main Deployment Logic
# -------------------------------------------------------------------


def get_user_confirmation(message: str) -> bool:
    """Get user confirmation for an action."""
    while True:
        response = input(f"{message} (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            return True
        if response in ['n', 'no']:
            return False
        print("Please answer 'y' or 'n'")


def handle_new_deployment(chosen_region: str, friendly: str) -> None:
    """Handle deployment when no instances are currently running."""
    print(
        f"\nℹ️ No instance deployed yet.\n⏳ Deploying to {chosen_region}...\n")

    if not get_user_confirmation(f"Proceed with deployment to {chosen_region} ({friendly})?"):
        print("Deployment cancelled by user.")
        return

    deploy_to_region(chosen_region, {})


def deploy_to_region(region: str, old_deployments: dict):
    """Handle deployment to region and cleanup of old instances."""
    # Deploy new instance
    update_tfvars(region)
    run_terraform(region)

    # Check deployment success
    instance_ip = get_terraform_output("instance_public_ip")
    if not instance_ip:
        print("❌ Failed to get instance IP from Terraform output")
        return

    instance_id = get_terraform_output("instance_id")
    if not instance_id:
        print("❌ Failed to get instance ID from Terraform output")
        return

    print(
        f"ℹ️ Checking HTTP availability on the new instance IP: {instance_ip}...")
    log_message(
        f"New instance deployed. IP: '{instance_ip}'. ID: '{instance_id}'. "
        "Running HTTP check before continuing...",
        region=region
    )

    if not wait_for_http_ok(instance_ip):
        print("❌ New instance failed health check")
        return

    if not (MYAPP_DOMAIN and HOSTED_ZONE_ID):
        print("ℹ️ Skipping DNS update - domain or zone ID not configured")
        return

    # Update DNS record
    print(f"⏳ Updating DNS A record of {MYAPP_DOMAIN} → {instance_ip}...")
    update_dns_record(
        instance_ip, MYAPP_DOMAIN, HOSTED_ZONE_ID, DNS_TTL, region=region
    )
    print("ℹ️ DNS record updated!\n\nℹ️ Redeployment complete. Starting cleanup...")
    log_message(
        "Redeployment process complete.\n",
        region="SYSTEM"
    )

    # Cleanup old instances and security groups
    log_message("Starting cleanup process...", region="SYSTEM")
    if old_deployments:
        for old_region, instances in old_deployments.items():
            if old_region != region:
                for inst_id in instances:
                    terminate_instance(inst_id, old_region)
                    remove_security_groups(old_region)
        log_message(
            "Cleanup complete. Successfully deleted old instances and security groups.\n",
            region="SYSTEM"
        )
    else:
        log_message(
            "No old instances found to clean up.\n",
            region="SYSTEM"
        )


def deploy():
    """Interactive deployment based on carbon intensity."""
    # 1. Get carbon intensities and show recommendations
    carbon_data = {}
    for aws_region, map_zone in AWS_REGIONS.items():
        intensity = get_carbon_intensity(map_zone)
        friendly = REGION_FRIENDLY_NAMES.get(aws_region, aws_region)
        print(
            f"🌍 '{aws_region}' ({friendly}) current carbon intensity: {intensity} gCO₂/kWh.")
        carbon_data[aws_region] = intensity

    best_region = min(carbon_data, key=carbon_data.get)
    best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
    print(f"\n⚡ Recommended AWS Region (lowest carbon intensity): '{best_region}' "
          f"({best_friendly}) - {carbon_data[best_region]} gCO₂/kWh.\n")

    # 2. Check existing deployments
    deployments = {
        region: instances for region in AWS_REGIONS
        if (instances := get_old_instances(region))
    }

    for region, instances in deployments.items():
        friendly = REGION_FRIENDLY_NAMES.get(region, region)
        print(
            f"ℹ️ Found running instance(s) in '{region}' ({friendly}): {instances}.")

    # 3. Get user decision
    if not get_user_confirmation("\n➡️ Would you like to deploy/redeploy an instance?"):
        return

    # 4. Region selection
    print("\nAvailable regions:")
    for i, (region, friendly) in enumerate(REGION_FRIENDLY_NAMES.items(), 1):
        print(f"{i}. '{region}' ({friendly}) - {carbon_data[region]} gCO₂/kWh")

    chosen_region = list(AWS_REGIONS.keys())[
        get_region_choice(len(AWS_REGIONS)) - 1]
    friendly = REGION_FRIENDLY_NAMES.get(chosen_region, chosen_region)
    print(f"\nℹ️ Selected: '{chosen_region}' ({friendly})")

    # Log the start of redeployment if needed
    if deployments:
        log_message(
            f"Lower carbon region detected: '{chosen_region}'. Starting redeployment process...",
            region="SYSTEM"
        )

    # 5. Deploy and cleanup
    deploy_to_region(chosen_region, deployments)


def get_region_choice(max_regions: int) -> int:
    """Get valid region selection from user."""
    while True:
        try:
            choice = int(input("\n➡️ Select region number: "))
            if 1 <= choice <= max_regions:
                return choice
            print(f"Please enter a number between 1 and {max_regions}")
        except ValueError:
            print("Please enter a valid number")


def run_main():
    """Runs the main code and returns execution time."""
    start_time = time.perf_counter()
    deploy()
    execution_time = time.perf_counter() - start_time
    print(f"ℹ️ Execution time: {execution_time:.2f} seconds.")

    # Create log message parts
    time_msg = f"Execution time: {execution_time:.2f} seconds."
    separator = "-" * 115
    log_message(
        f"{time_msg}\n\n{separator}\n",
        region="SYSTEM"
    )
    return execution_time


if __name__ == "__main__":
    run_main()
