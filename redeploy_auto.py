"""
Carbon-aware deployment automation script that moves AWS EC2 instances 
between regions based on real-time carbon intensity data from Electricity Maps.
"""

# Standard library imports
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
import sys

# Third-party imports
import requests
from dotenv import load_dotenv

# Load environment variables (from .env or system environment)
load_dotenv()

# ElectricityMaps configuration
ELECTRICITY_MAPS_API_TOKEN = "https://api.electricitymap.org/v3/carbon-intensity/latest"
AUTH_TOKEN = os.getenv("ELECTRICITYMAPS_API_TOKEN", "")

# DNS updates for Route53:
HOSTED_ZONE_ID = os.getenv("HOSTED_ZONE_ID", "")
MYAPP_DOMAIN = os.getenv("DOMAIN_NAME", "")
DNS_TTL = int(os.getenv("DNS_TTL", "60"))

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
TERRAFORM_DIR = SCRIPT_DIR / "terraform"
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)  # Create the logs dir if missing

# AWS Regions + Mapping to Electricity Map Zones
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

# Configure logging
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


# Functions for Carbon intensity + Region selection
def get_carbon_intensity(region_code: str) -> float:
    """
    Fetch the carbon intensity for a given zone (e.g., 'IE', 'GB', 'DE')
    from the Electricity Maps API.
    """
    headers = {"auth-token": AUTH_TOKEN}
    try:
        # First, check if we have a valid token
        if not AUTH_TOKEN:
            print("❌ API ACCESS ERROR: No valid API token provided")
            return float("inf")

        response = requests.get(
            f"{ELECTRICITY_MAPS_API_TOKEN}?zone={region_code}",
            headers=headers,
            timeout=10  # Add timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get("carbonIntensity", float("inf"))
    except requests.exceptions.RequestException as exc:
        # Use stderr to ensure the error is captured in output
        print(
            f"❌ API ACCESS ERROR: Failed to get data for {region_code}: {exc}", file=sys.stderr)
        print(f"❌ Error fetching data for {region_code}: {exc}")
        # Log more prominently for tests to detect
        print(f"❌ API ACCESS ERROR: Error fetching data for {region_code}")
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
        print(f"🌍 '{aws_region}' ({friendly_name}) current carbon intensity: "
              f"{intensity} gCO₂/kWh")
        log_message(
            f"{friendly_name}'s current carbon intensity: {intensity} gCO2/kWh",
            region=aws_region
        )
        carbon_data[aws_region] = intensity

    best_region = min(carbon_data, key=carbon_data.get)
    best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
    carbon_intensity_of_best_region = carbon_data[best_region]
    print(f"⚡ Recommended AWS Region (lowest carbon intensity): '{best_region}' "
          f"({best_friendly}) - {carbon_intensity_of_best_region} gCO₂/kWh.")
    return best_region


# Functions to manage EC2 Instances + Terraform
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
            f"Error fetching instances in {region}: {e}", region=region, level="error")
        return []


def check_existing_deployments():
    """
    Check all AWS regions for running instances with the tag 'myapp-instance'.
    Returns a dict: { region: [instance_ids], ... }.
    """
    deployments = {}
    found_instances = []

    for region in AWS_REGIONS:  # Iterate directly over dictionary
        if instance_ids := get_old_instances(region):
            friendly_region = REGION_FRIENDLY_NAMES.get(region, region)
            found_instances.append(
                f"'{region}' ({friendly_region}): {instance_ids}")
            deployments[region] = instance_ids

    if found_instances:
        print(f"✅ Found running instance(s) in: {', '.join(found_instances)}.")

    return deployments


def terminate_instance(instance_id: str, region: str):
    """
    Terminate an EC2 instance in the specified AWS region
    and block until the instance is fully terminated.
    """

    # Step 1: Terminate the instance
    terminate_cmd = [
        "aws", "ec2", "terminate-instances",
        "--instance-ids", instance_id,
        "--region", region,
        "--no-cli-pager",
        "--output", "text"
    ]
    terminate_result = subprocess.run(
        terminate_cmd, capture_output=True, text=True, check=True)

    if terminate_result.returncode == 0:
        print(
            f"⏳ Terminating instance {instance_id} in {region}..."
        )
        log_message(
            f"Started termination of instance '{instance_id}'...",
            region=region
        )
    else:
        print(f"❌ Failed to terminate instance {instance_id} in {region}. "
              f"Error: {terminate_result.stderr}")
        log_message(
            f"Failed to terminate instance {instance_id} in {region}. "
            f"Error: {terminate_result.stderr}",
            region=region, level="error"
        )
        return

    # Step 2: Wait until instance is fully terminated
    wait_cmd = [
        "aws", "ec2", "wait", "instance-terminated",
        "--instance-ids", instance_id,
        "--region", region
    ]
    wait_result = subprocess.run(
        wait_cmd, capture_output=True, text=True, check=True)
    if wait_result.returncode == 0:
        print(f"✅ Instance {instance_id} in {region} is fully terminated.\n")
        log_message(
            f"Instance '{instance_id}' is fully terminated.\n",
            region=region
        )
    else:
        print(
            f"❌ Wait for instance {instance_id} termination failed. "
            f"Error: {wait_result.stderr}"
        )
        log_message(
            f"Wait for instance {instance_id} termination failed. "
            f"Error: {wait_result.stderr}",
            region=region, level="error"
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
    # Validate region
    if region not in AWS_REGIONS:
        raise ValueError(
            f"Invalid region: {region}. Must be one of {', '.join(AWS_REGIONS.keys())}")

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
            log_message(f"Successfully deleted SG '{sg_id}'.", region=region)
        else:
            print(
                f"❌ Failed to delete SG '{sg_id}' in '{region}'. Error: {result.stderr}")
            log_message(
                f"Failed to delete SG '{sg_id}' in '{region}'. Error: {result.stderr}",
                region=region,
                level="error"
            )


def update_tfvars(region: str):
    """
    Overwrite terraform.tfvars with the chosen region + a new deployment_id
    to force Terraform to create a fresh instance.
    """
    # Validate region
    if region not in AWS_REGIONS:
        raise ValueError(
            f"Invalid region: {region}. Must be one of {', '.join(AWS_REGIONS.keys())}")

    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    deployment_id = int(time.time())

    with open(tfvars_path, "w", encoding="utf-8") as f:
        f.write(f'aws_region = "{region}"\n')
        f.write(f'deployment_id = "{deployment_id}"\n')

    log_message(
        f"Updated Terraform variables: 'Region={region}', "
        f"'Deployment_ID={deployment_id}'.",
        region=region
    )


def run_terraform(deploy_region: str):
    """Execute Terraform commands to deploy infrastructure."""
    friendly_region = REGION_FRIENDLY_NAMES.get(deploy_region, deploy_region)
    print(
        f"🔄 Running Terraform deployment in '{deploy_region}' "
        f"({friendly_region})."
    )

    print("⏳ Applying Terraform configuration. This may take a few minutes...\n")

    log_file_path = LOGS_DIR / "terraform.log"
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        subprocess.run(
            ["terraform", "init", "-upgrade", "-no-color"],
            cwd=TERRAFORM_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        subprocess.run(
            ["terraform", "apply", "-compact-warnings",
                "-auto-approve", "-no-color"],
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
        f"❌ Failed to retrieve Terraform output '{output_var}': "
        f"{result.stderr}"
    )
    return None

# HTTP Health Check


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
            logging.debug("HTTP request exception for %s: %s",
                          url, e)  # Fix f-string in logging

        print(
            f"⏳ Attempt {attempt}/{max_attempts}: "
            f"waiting for HTTP 200 from {url}..."
        )
        time.sleep(interval)

    print(f"❌ Gave up waiting for a successful HTTP response from {url}.")
    log_message(
        f"Gave up waiting for a successful HTTP response from {url}. Aborting.",
        region="SYSTEM",
        level="error"
    )
    return False

# DNS Update via Route53


def update_dns_record(new_ip: str, domain: str, zone_id: str, ttl: int = 60, region="N/A"):
    """
    Update a Route53 A record (myapp.example.com) to point to 'new_ip'.
    """
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
            f"Failed to update DNS record '{domain}'!",
            region=region,
            level="error"
        )
    else:
        print(
            f"ℹ️ Updated DNS A record of {domain} → {new_ip}. "
            f"Waiting {DNS_TTL} seconds to ensure complete DNS propagation...\n"
        )
        log_message(
            f"Updated DNS A record of '{domain}' to '{new_ip}'. "
            f"Waiting {DNS_TTL} seconds to ensure complete DNS propagation...",
            region=region
        )
        time.sleep(DNS_TTL)


# Main Deployment Logic

def cleanup_old_instances(old_deployments: dict, current_region: str):
    """Clean up old instances and security groups in regions other than current_region."""
    for old_region, instances in old_deployments.items():
        if old_region == current_region:
            continue

        for inst_id in instances:
            terminate_instance(inst_id, old_region)
            cleanup_security_groups(old_region)


def cleanup_security_groups(region: str):
    """Clean up security groups in the specified region."""
    try:
        if find_old_sgs(region):
            remove_security_groups(region)
        else:
            print(f"✅ No security groups found to clean up in {region}.")
            log_message("No security groups found to clean up.", region=region)
    except subprocess.CalledProcessError as e:
        print(
            f"❌ Failed to remove security groups in {region}. Error: {e}. Aborting.")
        log_message(
            f"Failed to remove security groups in {region}. Error: {e}. Aborting.",
            region=region,
            level="error"
        )


def deploy_to_region(region: str, old_deployments: dict):
    """Handle deployment to region and cleanup of old instances."""
    # Deploy new instance
    update_tfvars(region)
    run_terraform(region)

    # Check deployment success
    instance_ip = get_terraform_output("instance_public_ip")
    instance_id = get_terraform_output("instance_id")

    if not instance_ip or not instance_id:
        print("❌ Failed to get instance details from Terraform output!")
        log_message(
            "Failed to get instance details from Terraform output. Aborting.",
            region="SYSTEM",
            level="error"
        )
        return

    print("ℹ️ Checking HTTP availability on the new instance...")
    log_message(
        f"New instance deployed. IP: '{instance_ip}'. ID: '{instance_id}'.",
        region=region
    )
    log_message(
        "Running HTTP check before continuing, waiting for HTTP 200 response...",
        region=region
    )

    # Wait for HTTP check to complete
    if not wait_for_http_ok(instance_ip):
        print("❌ New instance failed health check!")
        log_message(
            "New instance failed health check. Aborting.",
            region="SYSTEM",
            level="error"
        )
        return

    if not (MYAPP_DOMAIN and HOSTED_ZONE_ID):
        print("ℹ️ Skipping DNS update - domain or zone ID not configured!")
        log_message(
            "Skipping DNS update - domain or zone ID not configured.",
            region="SYSTEM"
        )
        return

    # Update DNS record
    update_dns_record(
        new_ip=instance_ip,
        domain=MYAPP_DOMAIN,
        zone_id=HOSTED_ZONE_ID,
        ttl=DNS_TTL,
        region=region
    )
    print("ℹ️ Redeployment complete. Starting cleanup...")
    log_message("Redeployment process complete.\n", region="SYSTEM")

    # Cleanup old instances and security groups
    log_message("Starting cleanup process...", region="SYSTEM")
    if old_deployments:
        cleanup_old_instances(old_deployments, region)
        print("✅ Cleanup complete. Deleted old instances and security groups.")
        print(
            f"Application availabile at {MYAPP_DOMAIN} ({instance_ip}). Exiting.\n")
        log_message(
            "Cleanup complete. Successfully deleted old instances and security groups.",
            region="SYSTEM"
        )
        log_message(
            f"ℹ️ Application availabile at {MYAPP_DOMAIN} ({instance_ip}). Exiting.\n",
            region="SYSTEM"
        )
    else:
        handle_no_old_instances()


def handle_no_old_instances():
    """
    Handle case when no old instances are found to clean up.
    Logs appropriate messages and checks for any orphaned security groups
    across all AWS regions that may need to be cleaned up.
    """
    print("✅ No old instances found to clean up. Exiting.\n")
    log_message("No old instances found to clean up.\n", region="SYSTEM")

    # Check for any security groups to clean up even if no instances exist
    print("ℹ️ Checking for security groups to clean up...")
    log_message("Checking for security groups to clean up...",
                region="SYSTEM")

    any_sgs_found = False
    for region_name in AWS_REGIONS:
        old_sgs = find_old_sgs(region_name)
        if not old_sgs:
            continue

        any_sgs_found = True
        print(
            f"ℹ️ Found security groups in '{region_name}' to clean up: {old_sgs}")
        log_message(
            f"Found security groups in '{region_name}' to clean up: {old_sgs}",
            region=region_name
        )
        try:
            remove_security_groups(region_name)
        except subprocess.CalledProcessError as e:
            print(
                f"❌ Failed to remove security groups in {region_name}. Error: {e}. Aborting.")
            log_message(
                f"Failed to remove security groups in {region_name}. Error: {e}. Aborting.",
                region=region_name,
                level="error"
            )

    if not any_sgs_found:
        print("✅ No security groups found to clean up in any region.")
        log_message(
            "No security groups found to clean up in any region. "
            "Cleanup complete.\n", region="SYSTEM")


def deploy():
    """
    Automates instance deployment based on carbon intensity,
    fully non-interactive. Automatically uses the lowest-carbon region,
    then attempts to redeploy if that region differs from what's currently deployed.
    """
    # 1. Get carbon intensities and show recommendations
    carbon_data = {}
    api_accessible = True

    for aws_region, map_zone in AWS_REGIONS.items():
        intensity = get_carbon_intensity(map_zone)
        if intensity == float("inf"):
            api_accessible = False
        carbon_data[aws_region] = intensity
        friendly = REGION_FRIENDLY_NAMES.get(aws_region, aws_region)
        print(
            f"🌍 '{aws_region}' ({friendly}) current carbon intensity: "
            f"{intensity} gCO₂/kWh."
        )

    if not api_accessible:
        print("\n⚠️  ElectricityMaps API is not accessible. "
              "Falling back to default region (eu-west-2).")
        print("❌ API ACCESS ERROR: Falling back to default region due to API failure")
        log_message(
            "ElectricityMaps API not accessible, falling back to default region",
            region="SYSTEM"
        )
        best_region = "eu-west-2"  # Default to London
    else:
        best_region = min(carbon_data, key=carbon_data.get)
        best_friendly = REGION_FRIENDLY_NAMES.get(best_region, best_region)
        print(
            f"\n⚡ Recommended AWS Region (lowest carbon intensity): '{best_region}' "
            f"({best_friendly}) - {carbon_data[best_region]} gCO₂/kWh.\n"
        )

    # 2. Check existing deployments
    deployments = {
        region: instances for region in AWS_REGIONS
        if (instances := get_old_instances(region))
    }

    for region, instances in deployments.items():
        friendly = REGION_FRIENDLY_NAMES.get(region, region)
        print(
            f"ℹ️ Found running instance(s) in '{region}' "
            f"({friendly}): {instances}."
        )

    # Check if we're already in the greenest region
    if best_region in deployments:
        print(
            f"✅ Already in the {'lowest carbon' if api_accessible else 'default'} "
            f"region available: '{best_region}' "
            f"({REGION_FRIENDLY_NAMES.get(best_region, best_region)}). "
            "No need to redeploy. Exiting.\n"
        )
        log_message(
            f"Already in the {'lowest carbon' if api_accessible else 'default'} "
            f"region available: '{best_region}'. "
            "No need to redeploy. Exiting.",
            region="SYSTEM"
        )
        return

    # Log the start of redeployment if needed
    if deployments:
        print(f"ℹ️ {'Lower carbon region detected' if api_accessible else 'Default region'}: "
              f"'{best_region}'. "
              "Starting redeployment process...\n")
        log_message(
            f"{'Lower carbon region detected' if api_accessible else 'Default region'}: "
            f"'{best_region}'. Starting redeployment process...",
            region="SYSTEM"
        )

    # 3. Deploy and cleanup
    deploy_to_region(best_region, deployments)


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
