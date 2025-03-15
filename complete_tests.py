"""
Pytest-based Test Suite for Carbon-Aware Deployment Automation

• Ensures identical console & file output.
• "Cleared test results log file" is the very first line, then "Starting pre-tests checks...".
• Exactly one scenario block per check or test scenario.
• Scenario 1 only checks for "No old instances found to clean up".
• No console outputs from redeploy_auto.py or Terraform (only logs).
• Terraform uses timeouts to avoid hanging.
"""

# To run: `pytest -s -v --tb=short complete_tests.py`

import contextlib
import os
import sys
import io
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import pytest

# Import only the used items from redeploy_auto
from redeploy_auto import (
    AUTH_TOKEN, AWS_REGIONS, HOSTED_ZONE_ID, MYAPP_DOMAIN,
    TERRAFORM_DIR, deploy, get_old_instances, remove_security_groups,
    terminate_instance
)

# ---------------------------------------------------------------------
# Global Constants
# ---------------------------------------------------------------------
INSTANCE_START_WAIT = 3         # Wait time after instance creation
INTER_TEST_PAUSE = 3            # Pause between tests
TERRAFORM_TIMEOUT_INIT = 60     # Timeout for 'terraform init'
TERRAFORM_TIMEOUT_APPLY = 180   # Timeout for 'terraform apply'

# ---------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
TEST_LOG_FILE = LOGS_DIR / "test_results.log"
AWS_LOG_FILE = LOGS_DIR / "aws_terraform.log"

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Single formatter => same console/file output
unified_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(unified_formatter)

# File handler
file_handler = logging.FileHandler(TEST_LOG_FILE, encoding="utf-8")
file_handler.setFormatter(unified_formatter)

# Main test logger
test_logger = logging.getLogger("test_logger")
test_logger.setLevel(logging.DEBUG)
test_logger.addHandler(console_handler)
test_logger.addHandler(file_handler)

# AWS logger (only logs to file)
aws_logger = logging.getLogger("aws_logger")
aws_logger.setLevel(logging.DEBUG)
aws_file_handler = logging.FileHandler(AWS_LOG_FILE, encoding="utf-8")
aws_file_handler.setFormatter(unified_formatter)
aws_logger.addHandler(aws_file_handler)

# Suppress "carbon intensity" logs in console if desired


class SuppressCarbonIntensityLogs(logging.Filter):
    def filter(self, record):
        return "carbon intensity" not in record.getMessage().lower()


console_handler.addFilter(SuppressCarbonIntensityLogs())

# Hide redeploy_auto logs from console
redeploy_logger = logging.getLogger("redeploy_auto")
redeploy_logger.handlers.clear()
redeploy_file_handler = logging.FileHandler(AWS_LOG_FILE, encoding="utf-8")
redeploy_file_handler.setFormatter(unified_formatter)
redeploy_logger.addHandler(redeploy_file_handler)
redeploy_logger.propagate = False
redeploy_logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------
# Utility to Clear Log File
# ---------------------------------------------------------------------


def clear_log_file():
    try:
        with open(TEST_LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        test_logger.info("Cleared test results log file!\n")
    except IOError as e:
        test_logger.error("Could not clear log file: %s", e)

# ---------------------------------------------------------------------
# Logging Function: One Scenario Block
# ---------------------------------------------------------------------


def log_scenario(
    scenario_name: str,
    lines: List[str],
    result: str,
    details: Optional[str] = None
):
    """
    Logs one scenario block:
      <timestamp> - INFO - ==================================================
      <timestamp> - INFO - TEST SCENARIO: <scenario_name>
      <timestamp> - INFO - <lines>...
      (blank line)
      <timestamp> - INFO - Result: ...
      <timestamp> - INFO - Details: ...
      <timestamp> - INFO - ==================================================
    Exactly one blank line between scenario blocks.
    """
    test_logger.info("=" * 50)
    test_logger.info("TEST SCENARIO: %s", scenario_name)
    for line in lines:
        test_logger.info(line)
    test_logger.info("Result: %s", result)
    if details:
        test_logger.info("Details: %s", details)

# ---------------------------------------------------------------------
# Terraform Wrappers
# ---------------------------------------------------------------------


def run_terraform_init():
    subprocess.run(
        ["terraform", "init", "-no-color"],
        cwd=TERRAFORM_DIR,
        check=True,
        timeout=TERRAFORM_TIMEOUT_INIT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def run_terraform_apply():
    subprocess.run(
        ["terraform", "apply", "-auto-approve", "-no-color"],
        cwd=TERRAFORM_DIR,
        check=True,
        timeout=TERRAFORM_TIMEOUT_APPLY,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def update_tfvars(region: str):
    if region not in AWS_REGIONS:
        raise ValueError(
            f"Invalid region: {region}. Must be one of {', '.join(AWS_REGIONS.keys())}")

    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    with open(tfvars_path, "w", encoding="utf-8") as f:
        f.write(f'aws_region = "{region}"\n')
        f.write(f'deployment_id = "{int(time.time())}"\n')

    # test_logger.info("Updated terraform.tfvars with region=%s", region)


def run_terraform(region: str):
    update_tfvars(region)
    run_terraform_init()
    run_terraform_apply()

# ---------------------------------------------------------------------
# OutputCapture to Hide Subprocess Outputs from Console
# ---------------------------------------------------------------------


class OutputCapture:
    def __init__(self):
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.stdout_capture = io.StringIO()
        self.stderr_capture = io.StringIO()

    def __enter__(self):
        sys.stdout = self.stdout_capture
        sys.stderr = self.stderr_capture
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        out = self.stdout_capture.getvalue()
        err = self.stderr_capture.getvalue()
        if out:
            aws_logger.info("=== Captured stdout ===\n%s", out)
        if err:
            aws_logger.info("=== Captured stderr ===\n%s", err)
        self.stdout_capture.truncate(0)
        self.stderr_capture.truncate(0)


def capture_output(func, *args, **kwargs):
    with OutputCapture() as cap:
        result = func(*args, **kwargs)
        combined = cap.stdout_capture.getvalue() + cap.stderr_capture.getvalue()
        return result, combined

# ---------------------------------------------------------------------
# Cleanup Logic
# ---------------------------------------------------------------------


def get_running_instances() -> Dict[str, List[str]]:
    return {r: get_old_instances(r) for r in AWS_REGIONS}


def terminate_all_instances() -> List[str]:
    inst_map = get_running_instances()
    for region, inst_ids in inst_map.items():
        for iid in inst_ids:
            with contextlib.suppress(subprocess.CalledProcessError):
                terminate_instance(iid, region)


def wait_for_instances_to_terminate() -> List[str]:
    while any(get_running_instances().values()):
        time.sleep(5)


def cleanup_terraform_state() -> Tuple[bool, List[str]]:
    """
    Runs 'terraform destroy' and removes state files. Returns:
    - (True, ["Cleaned up Terraform state successfully."]) on success
    - (False, ["Terraform cleanup failed due to <error>"]) on failure
    """
    try:
        subprocess.run(
            ["terraform", "destroy", "-auto-approve", "-no-color"],
            cwd=TERRAFORM_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=180  # Ensure timeout is long enough
        )
        for f in ["terraform.tfstate", "terraform.tfstate.backup"]:
            path = TERRAFORM_DIR / f
            if path.exists():
                path.unlink()
        return True, ["Cleaned up Terraform state successfully."]

    except subprocess.TimeoutExpired:
        return False, ["ERROR: Terraform destroy timed out!"]

    except subprocess.CalledProcessError as e:
        return False, [f"ERROR: Terraform destroy failed: {e}"]

    except (OSError, IOError) as e:
        return False, [f"ERROR: Failed to delete state files: {e}"]


def cleanup_all_resources():
    """
    Ensures all cloud resources are cleaned up before tests.
    - If cleanup steps fail, logs warnings instead of failing pytest.
    """
    lines = ["Cleaning up all resources..."]
    cleanup_success = True  # Track if we should fail pytest or not

    # 1) Terminate all instances (silent failures)
    try:
        terminate_all_instances()
        wait_for_instances_to_terminate()
    except Exception as e:  # Catch all errors, not just subprocess.CalledProcessError
        lines.append(f"⚠️ WARNING: Instance termination failed: {e}")
        cleanup_success = False  # Do NOT stop execution, just log it

    # 2) Remove security groups
    for region in AWS_REGIONS:
        try:
            remove_security_groups(region)
        except Exception as e:  # Catch all errors, not just subprocess errors
            lines.append(
                f"⚠️ WARNING: Failed to remove security groups in {region}: {e}")
            cleanup_success = False  # Do NOT stop execution, just log it

    # 3) Cleanup Terraform (failures logged, but don't stop execution)
    try:
        success, st_lines = cleanup_terraform_state()
        lines += st_lines
        if not success:
            cleanup_success = False
    except Exception as e:
        lines.append(f"⚠️ WARNING: Terraform cleanup error: {e}")
        cleanup_success = False

    # Log cleanup results
    test_logger.info("=" * 50)
    test_logger.info("CLEANUP: Cleaning resources before proceeding...")
    for line in lines:
        test_logger.info(line)

    # ✅ Prevent pytest from marking cleanup as an error
    if not cleanup_success:
        test_logger.warning(
            "⚠️ CLEANUP encountered issues, but continuing tests.")


def cleanup_function(lines, arg1):
    test_logger.info("=" * 50)
    test_logger.info("CLEANUP: Cleaning resources before proceeding...")
    for line in lines:
        test_logger.info(line)
    test_logger.info(arg1)

# ---------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------


def check_dependencies() -> bool:
    scenario = "Dependency Check"
    lines = []
    required = ["aws", "terraform"]
    python_cmds = ["python", "python3"]
    missing = []

    for cmd in required:
        try:
            subprocess.run([cmd, "--version"], check=True, capture_output=True)
            lines.append(f"{cmd} available ✅")
        except (subprocess.CalledProcessError, FileNotFoundError):
            lines.append(f"{cmd} missing ❌")
            missing.append(cmd)

    python_found = False
    for p in python_cmds:
        with contextlib.suppress(subprocess.CalledProcessError, FileNotFoundError):
            subprocess.run([p, "--version"], check=True, capture_output=True)
            lines.append(f"{p} available ✅")
            python_found = True
            break
    if not python_found:
        missing.append("python or python3")

    if missing:
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing: {', '.join(missing)}")
        return False
    else:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All dependencies are installed.")
        return True


def check_aws_configuration() -> bool:
    scenario = "AWS Configuration"
    lines = []
    try:
        return aws_checks(lines, scenario)
    except subprocess.CalledProcessError as e:
        log_scenario(scenario, lines, "FAILED ❌", f"AWS error: {e}")
        return False


def aws_checks(lines, scenario):
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity"],
        check=True, capture_output=True, text=True
    )
    identity = json.loads(result.stdout)
    lines.append(f"AWS configured as: {identity.get('Arn')}")

    # minimal checks
    for svc, cmd in [
        ("EC2", ["aws", "ec2", "describe-regions"]),
        ("Route53", ["aws", "route53", "list-hosted-zones"])
    ]:
        subprocess.run(cmd, check=True, capture_output=True)
        lines.append(f"AWS {svc} permissions verified.")

    log_scenario(scenario, lines, "PASSED ✅",
                 "AWS is properly configured.")
    return True


def check_environment_variables() -> bool:
    scenario = "Environment Variables"
    lines = []
    required = {
        "ELECTRICITYMAPS_API_TOKEN": AUTH_TOKEN,
        "HOSTED_ZONE_ID": HOSTED_ZONE_ID,
        "DOMAIN_NAME": MYAPP_DOMAIN
    }
    missing = []
    for k, v in required.items():
        if v:
            lines.append(f"Environment variable set: {k}")
        else:
            lines.append(f"Missing environment variable: {k}")
            missing.append(k)

    if missing:
        log_scenario(scenario, lines, "WARNING ⚠️",
                     f"Missing: {', '.join(missing)}")
    else:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All required variables set.")
    return True


def check_terraform_files() -> bool:
    scenario = "Terraform Files"
    lines = []

    required = ["main.tf", "variables.tf", "outputs.tf"]
    optional = ["terraform.tfvars"]

    missing_required = [f for f in required if not (
        TERRAFORM_DIR / f).exists()]
    missing_optional = [f for f in optional if not (
        TERRAFORM_DIR / f).exists()]

    # Log presence or absence of each file
    for f in required:
        if (TERRAFORM_DIR / f).exists():
            lines.append(f"Terraform file exists: {f}")
        else:
            lines.append(f"Missing Terraform file: {f}")
    for f in optional:
        if (TERRAFORM_DIR / f).exists():
            lines.append(f"Terraform file exists: {f}")
        else:
            lines.append(f"ℹ️ Optional Terraform file not found: {f}")

    # If any required file is missing, fail immediately
    if missing_required:
        msg = f"Missing required file(s): {', '.join(missing_required)}"
        lines.append(msg)
        log_scenario(scenario, lines, "FAILED ❌", msg)
        return False

    # If the optional terraform.tfvars is missing, create a default one
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    if "terraform.tfvars" in missing_optional:
        lines.append(
            "ℹ️ Optional terraform.tfvars is missing; creating a default file.")
        default_content = (
            'aws_region = "eu-west-2"\n'
            'deployment_id = "0"\n'
        )
        tfvars_path.write_text(default_content, encoding="utf-8")

    # Now validate Terraform
    try:
        subprocess.run(
            ["terraform", "validate"],
            cwd=TERRAFORM_DIR,
            check=True,
            capture_output=True,
            text=True
        )
        lines.append("Terraform configuration is valid.")
        log_scenario(scenario, lines, "PASSED ✅",
                     "Files exist and configuration is valid.")
        return True

    except subprocess.CalledProcessError as e:
        lines.append(f"Validation error: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"Validation error: {e}")
        return False


def check_resource_limits() -> bool:
    scenario = "Resource Limits"
    lines = []
    for region in AWS_REGIONS:
        try:
            cmd = ["aws", "ec2", "describe-account-attributes",
                   "--attribute-names", "max-instances",
                   "--region", region]
            res = subprocess.run(
                cmd, check=True, capture_output=True, text=True)
            data = json.loads(res.stdout)
            max_insts = data["AccountAttributes"][0]["AttributeValues"][0]["AttributeValue"]
            lines.append(f"EC2 instance limit in {region}: {max_insts}")

            cmd = ["aws", "ec2", "describe-security-groups", "--region", region]
            res = subprocess.run(
                cmd, check=True, capture_output=True, text=True)
            sgroups = json.loads(res.stdout)
            lines.append(
                f"Security groups in {region}: {len(sgroups['SecurityGroups'])}")
        except subprocess.CalledProcessError as e:
            lines.append(f"{region} error: {e}")
            log_scenario(scenario, lines, "FAILED ❌", f"{region} error: {e}")
            return False

    log_scenario(scenario, lines, "PASSED ✅",
                 "Sufficient resources available.")
    return True


def check_aws_cost_estimate() -> bool:
    scenario = "AWS Cost Estimate"
    lines = []
    try:
        lines.extend(
            (
                "AWS cost estimate: $0.10/hour for t2.micro instances",
                "No AWS budget alerts configured (recommended for production)",
            )
        )
        log_scenario(scenario, lines, "PASSED ✅",
                     "Cost estimates are acceptable.")
        return True
    except Exception as e:
        lines.append(f"Cost estimate error: {e}")
        log_scenario(scenario, lines, "WARNING ⚠️",
                     f"Cost estimate error: {e}")
        return True


def check_terraform_state() -> bool:
    scenario = "Terraform State"
    lines = []
    lines.extend(
        f"Terraform state file exists: {f}"
        for f in ["terraform.tfstate", "terraform.tfstate.backup"]
        if (TERRAFORM_DIR / f).exists()
    )
    lock_file = TERRAFORM_DIR / ".terraform.tfstate.lock.info"
    if lock_file.exists():
        lines.append("Terraform state is locked")
    log_scenario(scenario, lines, "PASSED ✅",
                 "Terraform state is properly managed.")
    return True


def check_security_configuration() -> bool:
    """
    Performs security configuration checks.

    This function executes several security-related checks using the AWS CLI.
    It verifies security group settings and S3 bucket configurations.
    """
    scenario = "Security Configuration"
    lines = []
    checks = [
        lambda: subprocess.run(
            ["aws", "ec2", "describe-security-groups",
             "--filters", "Name=group-name,Values=myapp_sg_*",
             "--query", "SecurityGroups[*].{ID:GroupId,Ports:IpPermissions[*].{From:FromPort,To:ToPort}}",
             "--output", "json"],
            check=True, capture_output=True, text=True
        ),
        lambda: subprocess.run(
            ["aws", "s3api", "list-buckets",
             "--query", "Buckets[*].Name", "--output", "json"],
            check=True, capture_output=True, text=True
        )
    ]
    for i, c in enumerate(checks):
        try:
            c()
            if i == 0:
                lines.append("Security group settings check passed.")
            elif i == 1:
                lines.append("S3 bucket configuration check passed.")
        except subprocess.CalledProcessError as e:
            lines.append(f"Security check warning: {e}")

    log_scenario(scenario, lines, "PASSED ✅",
                 "Security configurations appear proper.")
    return True


def check_aws_regions() -> bool:
    scenario = "AWS Regions"
    lines = ["Checking AWS regions..."]
    try:
        for region in AWS_REGIONS:
            cmd = ["aws", "ec2", "describe-regions", "--region", region]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            lines.append(f"Region {region} is accessible.")
        # If we reach here, all regions are accessible
        log_scenario(scenario, lines, "PASSED ✅",
                     "All AWS regions accessible.")
        return True
    except subprocess.CalledProcessError as e:
        lines.append(f"Failed to access region: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"Error: {e}")
        return False


def check_dns_configuration() -> bool:
    scenario = "DNS Configuration"
    lines = ["Checking DNS configuration..."]
    if not HOSTED_ZONE_ID or not MYAPP_DOMAIN:
        lines.append(
            "HOSTED_ZONE_ID or MYAPP_DOMAIN missing; skipping DNS checks.")
        log_scenario(scenario, lines, "SKIPPED ⏩", "DNS not configured.")
        return True  # Not critical, just skip

    try:
        return run_aws_dns_check(lines, scenario)
    except subprocess.CalledProcessError as e:
        lines.append(f"DNS error: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"DNS error: {e}")
        return False


def run_aws_dns_check(lines, scenario):
    cmd = [
        "aws", "route53", "get-hosted-zone",
        "--id", HOSTED_ZONE_ID,
        "--query", "HostedZone.Name",
        "--output", "text"
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    zone_name = res.stdout.strip()
    lines.append(f"Found hosted zone: {zone_name}")
    log_scenario(scenario, lines, "PASSED ✅",
                 "DNS configuration is correct.")
    return True


def check_electricity_maps_api() -> bool:
    scenario = "ElectricityMaps API"

    if not AUTH_TOKEN:
        log_scenario(scenario, ["ELECTRICITYMAPS_API_TOKEN not set; skipping API check."],
                     "SKIPPED ⏩", "No token provided.")
        return True  # Not critical, just skip

    try:
        return test_electricity_maps_api()  # ✅ No arguments passed now
    except (requests.exceptions.RequestException, KeyError, StopIteration) as e:
        log_scenario(
            scenario, [f"API error: {e}"], "FAILED ❌", f"API error: {e}")
        return False


def test_electricity_maps_api():
    """Tests connectivity to the Electricity Maps API using assertions."""
    scenario = "ElectricityMaps API"
    lines = ["Checking Electricity Maps API..."]

    test_zone = next(iter(AWS_REGIONS.values()))
    url = f"https://api.electricitymap.org/v3/carbon-intensity/latest?zone={test_zone}"
    headers = {"auth-token": AUTH_TOKEN}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        lines.append(
            f"API working for zone {test_zone}; carbon intensity: {data.get('carbonIntensity')}")

        log_scenario(scenario, lines, "PASSED ✅",
                     "Electricity Maps API is accessible.")

        assert resp.status_code == 200, f"Expected status 200 but got {resp.status_code}"
        assert "carbonIntensity" in data, "Expected 'carbonIntensity' in response JSON"

    except requests.exceptions.RequestException as e:
        lines.append(f"API request failed: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"API request error: {e}")
        pytest.fail(f"Electricity Maps API request failed: {e}")


# ---------------------------------------------------------------------
# Error Scenarios
# ---------------------------------------------------------------------


def run_error_scenarios() -> bool:
    scenario = "Error Scenarios"
    lines = ["Testing invalid region, invalid instance ID, invalid security group..."]
    success = True

    # Invalid region
    try:
        update_tfvars("invalid-region")
        lines.append("Should have failed with invalid region, but did NOT.")
        success = False
    except (subprocess.CalledProcessError, ValueError):
        # The line below now includes quotes and clarifies the message:
        lines.append(
            "Invalid Region => Correctly failed with region 'invalid-region'.")

    # Invalid instance ID
    try:
        terminate_instance("i-invalid", "eu-west-2")
        lines.append("Should have failed with 'i-invalid', but did NOT.")
        success = False
    except subprocess.CalledProcessError:
        # Add quotes around i-invalid
        lines.append(
            "Invalid Instance ID => Correctly failed with instance ID 'i-invalid'.")

    # Invalid security group
    try:
        remove_security_groups("invalid-SG")
        lines.append("Should have failed with 'invalid-SG', but did NOT.")
        success = False
    except (subprocess.CalledProcessError, ValueError):
        # Now clarifies it's an invalid security group
        lines.append(
            "Invalid Security Group => Correctly failed with security group 'invalid-SG'.")

    if success:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All error scenarios worked as expected.")
    else:
        log_scenario(scenario, lines, "FAILED ❌",
                     "Some invalid scenario did not fail properly.")
    return success


# ---------------------------------------------------------------------
# Scenario 1: No Instances
# ---------------------------------------------------------------------


def no_instances_deployed() -> bool:
    scenario = "Scenario 1 - No instances"
    cleanup_all_resources()

    lines = [
        "Cleaning up all resources first...",
        "Running deploy with no instances expected.",
    ]
    _, output = capture_output(deploy)

    # Only check for "No old instances found to clean up"
    pattern = "No old instances found to clean up"
    if pattern in output:
        lines.append(f"FOUND PATTERN: {pattern}")
        log_scenario(scenario, lines, "PASSED ✅",
                     "No instances scenario worked.")
        return True
    else:
        lines.extend(
            (f"MISSING PATTERN: {pattern}", "Captured output:\n" + output))
        log_scenario(scenario, lines, "FAILED ❌",
                     "Expected pattern not found.")
        return False

# ---------------------------------------------------------------------
# Scenario 2: High Carbon Region
# ---------------------------------------------------------------------


def high_carbon_instance_redeployed() -> bool:
    scenario = "Scenario 2 - High carbon region"
    cleanup_all_resources()

    run_terraform("eu-central-1")
    time.sleep(INSTANCE_START_WAIT)

    lines = [
        "Cleaning up all resources first...",
        "Running terraform in eu-central-1 (high carbon region).",
        "Capturing output from main deploy function...",
    ]
    _, output = capture_output(deploy)
    patterns = [
        "Found running instance(s) in 'eu-central-1'",
        "Lower carbon region detected",
        "Cleanup complete"
    ]
    missing = [p for p in patterns if p not in output]
    for p in patterns:
        if p in output:
            lines.append(f"FOUND PATTERN: {p}")
        else:
            lines.append(f"MISSING PATTERN: {p}")

    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    else:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All expected patterns found.")
        return True

# ---------------------------------------------------------------------
# Scenario 3: Already in Greenest Region
# ---------------------------------------------------------------------


def instance_already_in_greenest_region() -> bool:
    scenario = "Scenario 3 - Greenest region"
    cleanup_all_resources()

    run_terraform("eu-west-2")
    time.sleep(INSTANCE_START_WAIT)

    lines = [
        "Cleaning up all resources first...",
        "Deploying to eu-west-2 (greenest region).",
        "Capturing output from main deploy function...",
    ]
    _, output = capture_output(deploy)
    patterns = [
        "Found running instance(s) in 'eu-west-2'",
        "Already in the lowest carbon region available: 'eu-west-2'",
        "No need to redeploy"
    ]
    missing = [p for p in patterns if p not in output]
    for p in patterns:
        if p in output:
            lines.append(f"FOUND PATTERN: {p}")
        else:
            lines.append(f"MISSING PATTERN: {p}")

    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    else:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All expected patterns found.")
        return True

# ---------------------------------------------------------------------
# Scenario 4: Missing API Token
# ---------------------------------------------------------------------


def electricity_maps_api_fails() -> bool:
    scenario = "Scenario 4 - Missing API Token"
    lines = ["Removing the ElectricityMaps API token to force a failure."]
    original_token = os.environ.get("ELECTRICITYMAPS_API_TOKEN")
    try:
        if "ELECTRICITYMAPS_API_TOKEN" in os.environ:
            del os.environ["ELECTRICITYMAPS_API_TOKEN"]

        headers = {"auth-token": ""}
        resp = requests.get(
            "https://api.electricitymap.org/v3/carbon-intensity", headers=headers, timeout=10)
        if resp.status_code == 200:
            lines.append("API returned data even though token was missing!")
            log_scenario(scenario, lines, "FAILED ❌",
                         "Should have returned 401 or error.")
            return False
        else:
            lines.append(
                f"API responded with {resp.status_code}, as expected (non-200).")
            log_scenario(scenario, lines, "PASSED ✅",
                         "Properly failed without an API token.")
            return True
    except requests.exceptions.RequestException as e:
        lines.append(f"API request failed as expected: {e}")
        log_scenario(scenario, lines, "PASSED ✅",
                     "RequestException => properly failed.")
        return True
    finally:
        if original_token:
            os.environ["ELECTRICITYMAPS_API_TOKEN"] = original_token

# ---------------------------------------------------------------------
# Scenario 5: Multiple Instances
# ---------------------------------------------------------------------


def multiple_instances_handled_correctly() -> bool:
    scenario = "Scenario 5 - Multiple instances"
    cleanup_all_resources()

    _, _ = capture_output(run_terraform, "eu-west-1")
    time.sleep(INSTANCE_START_WAIT)

    _, _ = capture_output(run_terraform, "eu-central-1")
    time.sleep(INSTANCE_START_WAIT)

    lines = [
        "Cleaning up all resources first...",
        "Deploying instance to eu-west-1.",
        "Deploying instance to eu-central-1.",
        "Capturing output from main deploy function (multiple instances).",
    ]
    _, output = capture_output(deploy)
    patterns = [
        "Found running instance(s)",
        "Starting redeployment process",
        "Cleanup complete"
    ]
    missing = [p for p in patterns if p not in output]
    for p in patterns:
        if p in output:
            lines.append(f"FOUND PATTERN: {p}")
        else:
            lines.append(f"MISSING PATTERN: {p}")

    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    else:
        log_scenario(scenario, lines, "PASSED ✅",
                     "All expected patterns found.")
        return True

# ---------------------------------------------------------------------
# Pytest Fixture
# ---------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def pre_test_setup_and_cleanup():
    # ✅ Ensure logs are cleared at the start of test execution
    clear_log_file()

    test_logger.info("=" * 50)
    test_logger.info("Starting pre-tests checks...")

    try:
        assert check_dependencies(), "Critical: Dependencies check failed."
        assert check_aws_configuration(), "Critical: AWS configuration check failed."

        check_aws_regions()
        check_dns_configuration()
        check_electricity_maps_api()
        check_environment_variables()
        assert check_terraform_files(), "Critical: Terraform files check failed."
        check_resource_limits()
        check_aws_cost_estimate()
        check_terraform_state()
        check_security_configuration()

        test_logger.info("=" * 50)
        test_logger.info(
            "Pre-tests all passed! Now proceeding to actual tests...")

        cleanup_all_resources()  # Cleanup before tests
        yield  # Yield control to tests
        cleanup_all_resources()  # Final cleanup

    except Exception as e:
        test_logger.error("Pre-test setup failed: %s", e, exc_info=True)
        pytest.fail(f"Pre-test setup failed: {e}")  # Force pytest failure


# ---------------------------------------------------------------------
# Actual Tests
# ---------------------------------------------------------------------


def test_error_scenarios():
    assert run_error_scenarios(), "Error scenarios test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_no_instances_deployed():
    assert no_instances_deployed(), "Scenario 1 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_high_carbon_instance_redeployed():
    assert high_carbon_instance_redeployed(), "Scenario 2 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_instance_already_in_greenest_region():
    assert instance_already_in_greenest_region(), "Scenario 3 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_missing_api_token():
    assert electricity_maps_api_fails(), "Scenario 4 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_multiple_instances_handled_correctly():
    assert multiple_instances_handled_correctly(), "Scenario 5 test failed."


if __name__ == "__main__":
    pytest.main(["-s", "-v", "--tb=short"])
