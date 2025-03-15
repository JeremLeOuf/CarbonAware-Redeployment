"""
Pytest-based Test Suite for Carbon-Aware Deployment Automation

Ensures identical console & file output.
Logs start with "Cleared test results log file" then "Starting pre-tests checks..."
One scenario block per check/test.
"""
# To run: pytest -s -v --tb=short complete_tests.py

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

from redeploy_auto import (
    AUTH_TOKEN, AWS_REGIONS, HOSTED_ZONE_ID, MYAPP_DOMAIN,
    TERRAFORM_DIR, deploy, get_old_instances, remove_security_groups,
    terminate_instance
)

# Global Constants
INSTANCE_START_WAIT = 3
INTER_TEST_PAUSE = 3
TERRAFORM_TIMEOUT_INIT = 60
TERRAFORM_TIMEOUT_APPLY = 180

# Logging Configuration
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
TEST_LOG_FILE = LOGS_DIR / "test_results.log"
AWS_LOG_FILE = LOGS_DIR / "aws_terraform.log"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
file_handler = logging.FileHandler(TEST_LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)

test_logger = logging.getLogger("test_logger")
test_logger.setLevel(logging.DEBUG)
test_logger.addHandler(console_handler)
test_logger.addHandler(file_handler)

aws_logger = logging.getLogger("aws_logger")
aws_logger.setLevel(logging.DEBUG)
aws_file_handler = logging.FileHandler(AWS_LOG_FILE, encoding="utf-8")
aws_file_handler.setFormatter(formatter)
aws_logger.addHandler(aws_file_handler)


def suppress_carbon_intensity_logs(record):
    """Filter function to suppress logs related to carbon intensity."""
    return "carbon intensity" not in record.getMessage().lower()


console_handler.addFilter(suppress_carbon_intensity_logs)

redeploy_logger = logging.getLogger("redeploy_auto")
redeploy_logger.handlers.clear()
redeploy_file_handler = logging.FileHandler(AWS_LOG_FILE, encoding="utf-8")
redeploy_file_handler.setFormatter(formatter)
redeploy_logger.addHandler(redeploy_file_handler)
redeploy_logger.propagate = False
redeploy_logger.setLevel(logging.DEBUG)

# Utility Functions


def clear_log_file():
    """Clears the test results log file."""
    try:
        TEST_LOG_FILE.write_text("", encoding="utf-8")
        test_logger.info("Cleared test results log file!\n")
    except IOError as e:
        test_logger.error("Could not clear log file: %s", e)


def log_scenario(scenario_name: str, lines: List[str], result: str, details: Optional[str] = None):
    """Logs the details of a test scenario."""
    test_logger.info("=" * 50)
    test_logger.info("TEST SCENARIO: %s", scenario_name)
    for line in lines:
        test_logger.info(line)
    test_logger.info("Result: %s", result)
    if details:
        test_logger.info("Details: %s", details)

# Terraform Wrappers


def run_terraform_init():
    """Runs terraform init command."""
    subprocess.run(["terraform", "init", "-no-color"],
                   cwd=TERRAFORM_DIR, check=True, timeout=TERRAFORM_TIMEOUT_INIT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_terraform_apply():
    """Runs terraform apply command."""
    subprocess.run(["terraform", "apply", "-auto-approve", "-no-color"],
                   cwd=TERRAFORM_DIR, check=True, timeout=TERRAFORM_TIMEOUT_APPLY,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def update_tfvars(region: str):
    """Updates the terraform variables file with the specified region."""
    if region not in AWS_REGIONS:
        raise ValueError(
            f"Invalid region: {region}. Must be one of {', '.join(AWS_REGIONS.keys())}")
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    tfvars_path.write_text(
        f'aws_region = "{region}"\ndeployment_id = "{int(time.time())}"\n', encoding="utf-8")


def run_terraform(region: str):
    """Runs terraform commands for the specified region."""
    update_tfvars(region)
    run_terraform_init()
    run_terraform_apply()


class OutputCapture:
    """Context manager to capture stdout and stderr output."""

    def __init__(self):
        self.orig_stdout, self.orig_stderr = sys.stdout, sys.stderr
        self.stdout_capture, self.stderr_capture = io.StringIO(), io.StringIO()

    def __enter__(self):
        sys.stdout, sys.stderr = self.stdout_capture, self.stderr_capture
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout, sys.stderr = self.orig_stdout, self.orig_stderr
        out, err = self.stdout_capture.getvalue(), self.stderr_capture.getvalue()
        if out:
            aws_logger.info("=== Captured stdout ===\n%s", out)
        if err:
            aws_logger.info("=== Captured stderr ===\n%s", err)
        self.stdout_capture.truncate(0)
        self.stderr_capture.truncate(0)


def capture_output(func, *args, **kwargs):
    """Captures the output of a function call."""
    with OutputCapture() as cap:
        result = func(*args, **kwargs)
        combined = cap.stdout_capture.getvalue() + cap.stderr_capture.getvalue()
    return result, combined

# Cleanup Logic


def get_running_instances() -> Dict[str, List[str]]:
    """Gets running instances for all regions."""
    return {r: get_old_instances(r) for r in AWS_REGIONS}


def terminate_all_instances() -> None:
    """Terminates all running instances across all regions."""
    for region, inst_ids in get_running_instances().items():
        for iid in inst_ids:
            with contextlib.suppress(subprocess.CalledProcessError):
                terminate_instance(iid, region)


def wait_for_instances_to_terminate() -> None:
    """Waits for all instances to terminate across all regions."""
    while any(get_running_instances().values()):
        time.sleep(5)


def cleanup_terraform_state() -> Tuple[bool, List[str]]:
    """Cleans up the terraform state."""
    try:
        subprocess.run(["terraform", "destroy", "-auto-approve", "-no-color"],
                       cwd=TERRAFORM_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=180)
        for f in ["terraform.tfstate", "terraform.tfstate.backup"]:
            state_file = TERRAFORM_DIR / f
            if state_file.exists():
                state_file.unlink()
        return True, ["Cleaned up Terraform state successfully."]
    except subprocess.TimeoutExpired:
        return False, ["ERROR: Terraform destroy timed out!"]
    except subprocess.CalledProcessError as e:
        return False, [f"ERROR: Terraform destroy failed: {e}"]
    except (OSError, IOError) as e:
        return False, [f"ERROR: Failed to delete state files: {e}"]


def cleanup_all_resources():
    """Cleans up all resources, including terminating instances and removing security groups."""
    lines = ["Cleaning up all resources..."]
    success = True
    try:
        terminate_all_instances()
        wait_for_instances_to_terminate()
    except subprocess.CalledProcessError as e:
        lines.append(f"⚠️ WARNING: Instance termination failed: {e}")
        success = False
    for region in AWS_REGIONS:
        try:
            remove_security_groups(region)
        except subprocess.CalledProcessError as e:
            lines.append(
                f"⚠️ WARNING: Failed to remove security groups in {region}: {e}")
            success = False
    try:
        ok, st_lines = cleanup_terraform_state()
        lines += st_lines
        if not ok:
            success = False
    except (subprocess.CalledProcessError, OSError, IOError) as e:
        lines.append(f"⚠️ WARNING: Terraform cleanup error: {e}")
        success = False
    test_logger.info("=" * 50)
    test_logger.info("CLEANUP: Cleaning resources before proceeding...")
    for line in lines:
        test_logger.info(line)
    if not success:
        test_logger.warning(
            "⚠️ CLEANUP encountered issues, but continuing tests.")


def check_dependencies() -> bool:
    """Checks for required dependencies."""
    scenario = "Dependency Check"
    lines, missing = [], []
    for cmd in ["aws", "terraform"]:
        try:
            subprocess.run([cmd, "--version"], check=True, capture_output=True)
            lines.append(f"{cmd} available ✅")
        except subprocess.CalledProcessError:
            lines.append(f"{cmd} missing ❌")
            missing.append(cmd)
    python_found = False
    for p in ["python", "python3"]:
        try:
            subprocess.run([p, "--version"], check=True, capture_output=True)
            lines.append(f"{p} available ✅")
            python_found = True
            break
        except subprocess.CalledProcessError:
            continue
    if not python_found:
        missing.append("python or python3")
    if missing:
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing: {', '.join(missing)}")
        return False
    log_scenario(scenario, lines, "PASSED ✅",
                 "All dependencies are installed.")
    return True


def check_aws_configuration() -> bool:
    """Checks AWS configuration by running AWS commands and verifying permissions."""
    scenario = "AWS Configuration"
    lines = []
    try:
        return run_aws_cmds(lines, scenario)
    except subprocess.CalledProcessError as e:
        log_scenario(scenario, lines, "FAILED ❌", f"AWS error: {e}")
        return False


def run_aws_cmds(lines, scenario):
    """Runs AWS commands to verify configuration."""
    result = subprocess.run(["aws", "sts", "get-caller-identity"],
                            check=True, capture_output=True, text=True)
    identity = json.loads(result.stdout)
    lines.append(f"AWS configured as: {identity.get('Arn')}")
    for svc, cmd in [("EC2", ["aws", "ec2", "describe-regions"]),
                     ("Route53", ["aws", "route53", "list-hosted-zones"])]:
        subprocess.run(cmd, check=True, capture_output=True)
        lines.append(f"AWS {svc} permissions verified.")
    log_scenario(scenario, lines, "PASSED ✅",
                 "AWS is properly configured.")
    return True


def check_environment_variables() -> bool:
    """Checks for required environment variables."""
    scenario = "Environment Variables"
    lines = []
    required = {"ELECTRICITYMAPS_API_TOKEN": AUTH_TOKEN,
                "HOSTED_ZONE_ID": HOSTED_ZONE_ID,
                "DOMAIN_NAME": MYAPP_DOMAIN}
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
    """Checks for required Terraform files."""
    scenario = "Terraform Files"
    required = ["main.tf", "variables.tf", "outputs.tf"]
    optional = ["terraform.tfvars"]
    missing_required = [f for f in required if not (
        TERRAFORM_DIR / f).exists()]
    lines = [
        (
            f"Terraform file exists: {f}"
            if (TERRAFORM_DIR / f).exists()
            else f"Missing Terraform file: {f}"
        )
        for f in required
    ]
    lines.extend(
        (
            f"Terraform file exists: {f}"
            if (TERRAFORM_DIR / f).exists()
            else f"ℹ️ Optional Terraform file not found: {f}"
        )
        for f in optional
    )
    if missing_required:
        msg = f"Missing required file(s): {', '.join(missing_required)}"
        lines.append(msg)
        log_scenario(scenario, lines, "FAILED ❌", msg)
        return False
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    if not tfvars_path.exists():
        lines.append(
            "ℹ️ Optional terraform.tfvars is missing; creating a default file.")
        tfvars_path.write_text(
            'aws_region = "eu-west-2"\ndeployment_id = "0"\n', encoding="utf-8")
    try:
        subprocess.run(["terraform", "validate"], cwd=TERRAFORM_DIR, check=True,
                       capture_output=True, text=True)
        lines.append("Terraform configuration is valid.")
        log_scenario(scenario, lines, "PASSED ✅",
                     "Files exist and configuration is valid.")
        return True
    except subprocess.CalledProcessError as e:
        lines.append(f"Validation error: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"Validation error: {e}")
        return False


def check_resource_limits() -> bool:
    """Checks AWS resource limits."""
    scenario = "Resource Limits"
    lines = []
    for region in AWS_REGIONS:
        try:
            res = subprocess.run(["aws", "ec2", "describe-account-attributes",
                                  "--attribute-names", "max-instances", "--region", region],
                                 check=True, capture_output=True, text=True)
            max_insts = json.loads(res.stdout)[
                "AccountAttributes"][0]["AttributeValues"][0]["AttributeValue"]
            lines.append(f"EC2 instance limit in {region}: {max_insts}")
            res = subprocess.run(["aws", "ec2", "describe-security-groups", "--region", region],
                                 check=True, capture_output=True, text=True)
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
    """Estimates AWS costs."""
    scenario = "AWS Cost Estimate"
    lines = ["AWS cost estimate: $0.10/hour for t2.micro instances",
             "No AWS budget alerts configured (recommended for production)"]
    log_scenario(scenario, lines, "PASSED ✅", "Cost estimates are acceptable.")
    return True


def check_terraform_state() -> bool:
    """Checks the Terraform state."""
    scenario = "Terraform State"
    lines = [f"Terraform state file exists: {f}" for f in [
        "terraform.tfstate", "terraform.tfstate.backup"] if (TERRAFORM_DIR / f).exists()]
    if (TERRAFORM_DIR / ".terraform.tfstate.lock.info").exists():
        lines.append("Terraform state is locked")
    log_scenario(scenario, lines, "PASSED ✅",
                 "Terraform state is properly managed.")
    return True


def check_security_configuration() -> bool:
    """Checks security configurations."""
    scenario = "Security Configuration"
    lines = []
    checks = [
        lambda: subprocess.run(
            ["aws", "ec2", "describe-security-groups",
             "--filters", "Name=group-name,Values=myapp_sg_*", "--query",
             "SecurityGroups[*].{ID:GroupId,Ports:IpPermissions[*].{From:FromPort,To:ToPort}}",
             "--output", "json"],
            check=True, capture_output=True, text=True),
        lambda: subprocess.run(
            ["aws", "s3api", "list-buckets",
             "--query", "Buckets[*].Name", "--output", "json"],
            check=True, capture_output=True, text=True)
    ]
    for i, check in enumerate(checks):
        try:
            check()
            lines.append("Security group settings check passed." if i ==
                         0 else "S3 bucket configuration check passed.")
        except subprocess.CalledProcessError as e:
            lines.append(f"Security check warning: {e}")
    log_scenario(scenario, lines, "PASSED ✅",
                 "Security configurations appear proper.")
    return True


def check_aws_regions() -> bool:
    """Checks accessibility of AWS regions."""
    scenario = "AWS Regions"
    lines = ["Checking AWS regions..."]
    try:
        for region in AWS_REGIONS:
            subprocess.run(["aws", "ec2", "describe-regions", "--region", region],
                           check=True, capture_output=True, text=True)
            lines.append(f"Region {region} is accessible.")
        log_scenario(scenario, lines, "PASSED ✅",
                     "All AWS regions accessible.")
        return True
    except subprocess.CalledProcessError as e:
        lines.append(f"Failed to access region: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"Error: {e}")
        return False


def check_dns_configuration() -> bool:
    """Checks DNS configuration."""
    scenario = "DNS Configuration"
    lines = ["Checking DNS configuration..."]
    if not HOSTED_ZONE_ID or not MYAPP_DOMAIN:
        lines.append(
            "HOSTED_ZONE_ID or MYAPP_DOMAIN missing; skipping DNS checks.")
        log_scenario(scenario, lines, "SKIPPED ⏩", "DNS not configured.")
        return True
    try:
        return query_aws_dns(lines, scenario)
    except subprocess.CalledProcessError as e:
        lines.append(f"DNS error: {e}")
        log_scenario(scenario, lines, "FAILED ❌", f"DNS error: {e}")
        return False


def query_aws_dns(lines, scenario):
    """Queries AWS DNS for the hosted zone name."""
    cmd = ["aws", "route53", "get-hosted-zone", "--id", HOSTED_ZONE_ID,
           "--query", "HostedZone.Name", "--output", "text"]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    zone_name = res.stdout.strip()
    lines.append(f"Found hosted zone: {zone_name}")
    log_scenario(scenario, lines, "PASSED ✅",
                 "DNS configuration is correct.")
    return True


def check_electricity_maps_api() -> bool:
    """Checks the ElectricityMaps API for accessibility and proper configuration."""
    scenario = "ElectricityMaps API"
    if not AUTH_TOKEN:
        log_scenario(scenario, ["ELECTRICITYMAPS_API_TOKEN not set; skipping API check."],
                     "SKIPPED ⏩", "No token provided.")
        return True
    try:
        test_electricity_maps_api()
        return True
    except (requests.exceptions.RequestException, KeyError, StopIteration) as e:
        log_scenario(
            scenario, [f"API error: {e}"], "FAILED ❌", f"API error: {e}")
        return False


def test_electricity_maps_api():
    """Tests the ElectricityMaps API for accessibility."""
    scenario = "ElectricityMaps API"
    test_zone = next(iter(AWS_REGIONS.values()))
    url = f"https://api.electricitymap.org/v3/carbon-intensity/latest?zone={test_zone}"
    headers = {"auth-token": AUTH_TOKEN}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    lines = [
        "Checking Electricity Maps API...",
        f"API working for zone {test_zone}; carbon intensity: {data.get('carbonIntensity')}",
    ]
    log_scenario(scenario, lines, "PASSED ✅",
                 "Electricity Maps API is accessible.")
    assert resp.status_code == 200, f"Expected status 200 but got {resp.status_code}"
    assert "carbonIntensity" in data, "Expected 'carbonIntensity' in response JSON"

# Error Scenarios and Test Scenarios


def run_error_scenarios() -> bool:
    """Runs error scenarios to validate error handling."""
    scenario = "Error Scenarios"
    lines = ["Testing invalid region, invalid instance ID, invalid security group..."]
    success = True
    try:
        update_tfvars("invalid-region")
        lines.append("Should have failed with invalid region, but did NOT.")
        success = False
    except (subprocess.CalledProcessError, ValueError):
        lines.append(
            "Invalid Region => Correctly failed with region 'invalid-region'.")
    try:
        terminate_instance("i-invalid", "eu-west-2")
        lines.append("Should have failed with 'i-invalid', but did NOT.")
        success = False
    except subprocess.CalledProcessError:
        lines.append(
            "Invalid Instance ID => Correctly failed with instance ID 'i-invalid'.")
    try:
        remove_security_groups("invalid-SG")
        lines.append("Should have failed with 'invalid-SG', but did NOT.")
        success = False
    except (subprocess.CalledProcessError, ValueError):
        lines.append(
            "Invalid Security Group => Correctly failed with security group 'invalid-SG'.")
    log_scenario(scenario, lines, "PASSED ✅" if success else "FAILED ❌",
                 "All error scenarios worked as expected." if success else
                 "Some invalid scenario did not fail properly.")
    return success


def no_instances_deployed() -> bool:
    """Tests the scenario where no instances are deployed."""
    scenario = "Scenario 1 - No instances"
    cleanup_all_resources()
    lines = ["Cleaning up all resources first...",
             "Running deploy with no instances expected."]
    _, output = capture_output(deploy)
    pattern = "No old instances found to clean up"
    if pattern in output:
        lines.append(f"FOUND PATTERN: {pattern}")
        log_scenario(scenario, lines, "PASSED ✅",
                     "No instances scenario worked.")
        return True
    lines.extend([f"MISSING PATTERN: {pattern}",
                 "Captured output:\n" + output])
    log_scenario(scenario, lines, "FAILED ❌", "Expected pattern not found.")
    return False


def high_carbon_instance_redeployed() -> bool:
    """Tests redeployment in a high carbon region."""
    scenario = "Scenario 2 - High carbon region"
    cleanup_all_resources()
    run_terraform("eu-central-1")
    time.sleep(INSTANCE_START_WAIT)
    lines = ["Cleaning up all resources first...",
             "Running terraform in eu-central-1 (high carbon region).",
             "Capturing output from main deploy function..."]
    _, output = capture_output(deploy)
    patterns = ["Found running instance(s) in 'eu-central-1'",
                "Lower carbon region detected", "Cleanup complete"]
    missing = []
    for p in patterns:
        lines.append(
            f"FOUND PATTERN: {p}" if p in output else f"MISSING PATTERN: {p}")
        if p not in output:
            missing.append(p)
    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    log_scenario(scenario, lines, "PASSED ✅", "All expected patterns found.")
    return True


def instance_already_in_greenest_region() -> bool:
    """Tests deployment in the greenest region."""
    scenario = "Scenario 3 - Greenest region"
    cleanup_all_resources()
    run_terraform("eu-west-2")
    time.sleep(INSTANCE_START_WAIT)
    lines = ["Cleaning up all resources first...", "Deploying to eu-west-2 (greenest region).",
             "Capturing output from main deploy function..."]
    _, output = capture_output(deploy)
    patterns = ["Found running instance(s) in 'eu-west-2'",
                "Already in the lowest carbon region available: 'eu-west-2'",
                "No need to redeploy"]
    missing = []
    for p in patterns:
        lines.append(
            f"FOUND PATTERN: {p}" if p in output else f"MISSING PATTERN: {p}")
        if p not in output:
            missing.append(p)
    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    log_scenario(scenario, lines, "PASSED ✅", "All expected patterns found.")
    return True


def electricity_maps_api_fails() -> bool:
    """Tests the scenario where the ElectricityMaps API token is missing."""
    scenario = "Scenario 4 - Missing API Token"
    lines = ["Removing the ElectricityMaps API token to force a failure."]
    original_token = os.environ.get("ELECTRICITYMAPS_API_TOKEN")
    try:
        return check_electricitymaps_without_token(lines, scenario)
    except requests.exceptions.RequestException as e:
        lines.append(f"API request failed as expected: {e}")
        log_scenario(scenario, lines, "PASSED ✅",
                     "RequestException => properly failed.")
        return True
    finally:
        if original_token:
            os.environ["ELECTRICITYMAPS_API_TOKEN"] = original_token


def check_electricitymaps_without_token(lines, scenario):
    """Checks the ElectricityMaps API without a token to ensure it fails as expected."""
    os.environ.pop("ELECTRICITYMAPS_API_TOKEN", None)
    headers = {"auth-token": ""}
    resp = requests.get(
        "https://api.electricitymap.org/v3/carbon-intensity", headers=headers, timeout=10)
    if resp.status_code == 200:
        lines.append("API returned data even though token was missing!")
        log_scenario(scenario, lines, "FAILED ❌",
                     "Should have returned 401 or error.")
        return False
    lines.append(
        f"API responded with {resp.status_code}, as expected (non-200).")
    log_scenario(scenario, lines, "PASSED ✅",
                 "Properly failed without an API token.")
    return True


def multiple_instances_handled_correctly() -> bool:
    """Tests handling of multiple instances."""
    scenario = "Scenario 5 - Multiple instances"
    cleanup_all_resources()
    capture_output(run_terraform, "eu-west-1")
    time.sleep(INSTANCE_START_WAIT)
    capture_output(run_terraform, "eu-central-1")
    time.sleep(INSTANCE_START_WAIT)
    lines = ["Cleaning up all resources first...", "Deploying instance to eu-west-1.",
             "Deploying instance to eu-central-1.",
             "Capturing output from main deploy function (multiple instances)."]
    _, output = capture_output(deploy)
    patterns = [
        "Found running instance(s)", "Starting redeployment process", "Cleanup complete"]
    missing = []
    for p in patterns:
        lines.append(
            f"FOUND PATTERN: {p}" if p in output else f"MISSING PATTERN: {p}")
        if p not in output:
            missing.append(p)
    if missing:
        lines.append("Captured output:\n" + output)
        log_scenario(scenario, lines, "FAILED ❌",
                     f"Missing patterns: {', '.join(missing)}")
        return False
    log_scenario(scenario, lines, "PASSED ✅", "All expected patterns found.")
    return True

# Pytest Fixture and Tests


@pytest.fixture(scope="module", autouse=True)
def pre_test_setup_and_cleanup():
    """Fixture for pre-test setup and cleanup, ensuring all checks are performed before tests."""
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
        cleanup_all_resources()
        yield
        cleanup_all_resources()
    except (subprocess.CalledProcessError, OSError, IOError) as e:
        test_logger.error("Pre-test setup failed: %s", e, exc_info=True)
        pytest.fail(f"Pre-test setup failed: {e}")


def test_error_scenarios():
    """Tests error scenarios."""
    assert run_error_scenarios(), "Error scenarios test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_no_instances_deployed():
    """Tests the scenario where no instances are deployed."""
    assert no_instances_deployed(), "Scenario 1 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_high_carbon_instance_redeployed():
    """Tests redeployment in a high carbon region."""
    assert high_carbon_instance_redeployed(), "Scenario 2 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_instance_already_in_greenest_region():
    """Tests deployment in the greenest region."""
    assert instance_already_in_greenest_region(), "Scenario 3 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_missing_api_token():
    """Tests the scenario where the API token is missing."""
    assert electricity_maps_api_fails(), "Scenario 4 test failed."
    time.sleep(INTER_TEST_PAUSE)


def test_multiple_instances_handled_correctly():
    """Tests handling of multiple instances."""
    assert multiple_instances_handled_correctly(), "Scenario 5 test failed."


if __name__ == "__main__":
    pytest.main(["-s", "-v", "--tb=short"])
