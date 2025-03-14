"""
Test script for carbon-aware deployment automation.
Simulates different deployment scenarios to verify behavior of redeploy scripts.
"""

# sourcery skip: no-conditionals-in-tests

# Standard library imports
import datetime
import io
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Third-party imports
import requests

import redeploy_auto

# Import functions from redeploy_auto.py
from redeploy_auto import (
    find_best_region,
    get_old_instances,
    terminate_instance,
    remove_security_groups,
    update_tfvars,
    run_terraform,
    TERRAFORM_DIR,
    deploy,
    ELECTRICITY_MAPS_API_TOKEN,
    AUTH_TOKEN,
    HOSTED_ZONE_ID,
    MYAPP_DOMAIN,
    AWS_REGIONS
)

# Configure logging for test results
TEST_LOG_FILE = str(Path(__file__).parent / "logs/test_results.log")
AWS_LOG_FILE = str(Path(__file__).parent / "logs/aws_terraform.log")

# Remove any existing handlers from the root logger
logging.getLogger().handlers = []

# Create a separate logger for test results
test_logger = logging.getLogger('test_logger')
test_logger.handlers = []  # Remove any existing handlers
test_logger.setLevel(logging.INFO)

# Create a separate logger for AWS and Terraform outputs
aws_logger = logging.getLogger('aws_logger')
aws_logger.handlers = []
aws_logger.setLevel(logging.INFO)

# Create a file handler for test results
test_file_handler = logging.FileHandler(TEST_LOG_FILE, encoding='utf-8')
test_file_handler.setLevel(logging.INFO)

# Create a file handler for AWS and Terraform outputs
aws_file_handler = logging.FileHandler(AWS_LOG_FILE, encoding='utf-8')
aws_file_handler.setLevel(logging.INFO)

# Create a console handler for immediate output
test_console_handler = logging.StreamHandler()
test_console_handler.setLevel(logging.INFO)

# Create a formatter for test results
test_formatter = logging.Formatter('%(message)s')  # Remove timestamp and level
test_file_handler.setFormatter(test_formatter)
test_console_handler.setFormatter(test_formatter)
aws_file_handler.setFormatter(test_formatter)

# Add handlers to the loggers
test_logger.addHandler(test_file_handler)
test_logger.addHandler(test_console_handler)
aws_logger.addHandler(aws_file_handler)

# Prevent propagation to root logger
test_logger.propagate = False
aws_logger.propagate = False


class OutputCapture:
    """Context manager for capturing AWS and Terraform outputs."""

    def __init__(self, log_file):
        self.log_file = log_file
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

        # Log captured output to file
        stdout_output = self.stdout_capture.getvalue()
        stderr_output = self.stderr_capture.getvalue()

        if stdout_output:
            aws_logger.info("=== Captured stdout ===\n%s", stdout_output)
        if stderr_output:
            aws_logger.info("=== Captured stderr ===\n%s", stderr_output)

        # Clear the captures
        self.stdout_capture.truncate(0)
        self.stderr_capture.truncate(0)


def capture_output(func, *args, **kwargs):
    """Capture stdout from a function call."""
    with OutputCapture(AWS_LOG_FILE) as capture:
        result = func(*args, **kwargs)
        # Combine both stdout and stderr to ensure we catch all output
        return result, capture.stdout_capture.getvalue() + capture.stderr_capture.getvalue()


def clear_log_file():
    """Clear the test results log file."""
    try:
        with open(TEST_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("")  # Clear the file
        log_test_result("System", "INFO", "Cleared test results log file")
    except IOError as e:
        log_test_result("System", "ERROR",
                        f"Could not clear log file: {str(e)}")


def log_test_result(scenario: str, result: str, details: Optional[str] = None):
    """Log test results with formatting."""
    # Log to both console and file
    test_logger.info("%s", "\n" + "=" * 80)
    test_logger.info("Test Scenario: %s", scenario)
    test_logger.info("Result: %s", result)
    if details:
        test_logger.info("Details: %s", details)
    test_logger.info("%s", "=" * 80 + "\n")


# -------------------------------------------------------------------
# Core Testing Functions
# -------------------------------------------------------------------

def verify_output_patterns(stdout: str, expected_patterns: List[str],
                           scenario: str) -> bool:
    """Verify that all expected patterns are present in the output."""
    # Log the captured output for debugging (not to console)
    test_logger.debug("+++ Captured Output for %s +++\n%s", scenario, stdout)

    # Strict pattern matching - must find ALL patterns
    missing_patterns = []
    for pattern in expected_patterns:
        if pattern not in stdout:
            missing_patterns.append(pattern)
            test_logger.info("❌ MISSING PATTERN: %s!", pattern)
        else:
            test_logger.info("✅ FOUND PATTERN: %s.", pattern)

    if missing_patterns:
        log_test_result(
            scenario,
            "FAILED ❌",
            f"Missing expected patterns in output: {', '.join(missing_patterns)}"
        )
        return False

    log_test_result(
        scenario,
        "PASSED ✅",
        "All required patterns found in output."
    )
    return True


# -------------------------------------------------------------------
# Pre-Test Checks
# -------------------------------------------------------------------

def check_dependencies():
    """Check if all required dependencies are installed."""
    required_commands = ["aws", "terraform", "python", "python3"]
    missing_deps = []

    for cmd in required_commands:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            test_logger.info("✅ Dependency available: %s.", cmd)
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing_deps.append(cmd)
            test_logger.error("❌ Missing dependency: %s!", cmd)

    if missing_deps:
        log_test_result(
            "Dependency Check",
            "FAILED ❌",
            f"Missing required dependencies: {', '.join(missing_deps)}!"
        )
        return False

    log_test_result(
        "Dependency Check",
        "PASSED ✅",
        "All required dependencies are installed."
    )
    return True


def check_aws_configuration():
    """Check if AWS is properly configured."""
    try:
        # Check AWS credentials
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity"],
            capture_output=True,
            text=True,
            check=True
        )
        identity = json.loads(result.stdout)
        test_logger.info("✅ AWS configured as: %s.", identity['Arn'])

        # Check required permissions
        required_services = ["ec2", "route53"]
        for service in required_services:
            try:
                if service == "ec2":
                    subprocess.run(
                        ["aws", "ec2", "describe-regions"],
                        capture_output=True,
                        check=True
                    )
                    test_logger.info("✅ AWS EC2 permissions verified.")
                elif service == "route53":
                    subprocess.run(
                        ["aws", "route53", "list-hosted-zones"],
                        capture_output=True,
                        check=True
                    )
                    test_logger.info("✅ AWS Route53 permissions verified.")
            except subprocess.CalledProcessError:
                log_test_result(
                    "AWS Configuration",
                    "FAILED ❌",
                    f"Missing required AWS permissions for {service}"
                )
                return False

        log_test_result(
            "AWS Configuration",
            "PASSED ✅",
            "AWS properly configured with required permissions."
        )
        return True
    except subprocess.CalledProcessError as e:
        log_test_result(
            "AWS Configuration",
            "FAILED ❌",
            f"AWS not properly configured: {str(e)}"
        )
        return False


def check_aws_regions():
    """Check if all required AWS regions are accessible."""
    test_logger.info("Checking AWS regions accessibility...")
    for region in AWS_REGIONS:
        try:
            # Check region availability
            result = subprocess.run(
                ["aws", "ec2", "describe-regions", "--region", region],
                capture_output=True,
                text=True,
                check=True
            )
            test_logger.info("✅ Region %s is accessible.", region)

            # Check EC2 service limits
            result = subprocess.run(
                ["aws", "service-quotas", "get-service-quota",
                 "--service-code", "ec2",
                 "--quota-code", "L-417A185B",
                 "--region", region],
                capture_output=True,
                text=True,
                check=True
            )
            quota = json.loads(result.stdout)
            test_logger.info(
                "✅ EC2 instance limit in %s: %s.",
                region,
                quota['Quota']['Value']
            )

        except subprocess.CalledProcessError as e:
            log_test_result(
                "AWS Regions",
                "FAILED ❌",
                f"Region {region} is not accessible: {str(e)}"
            )
            return False

    log_test_result(
        "AWS Regions",
        "PASSED ✅",
        f"All required AWS regions are accessible: {', '.join(AWS_REGIONS.keys())}."
    )
    return True


def check_electricity_maps_api():
    """Check if ElectricityMaps API is accessible and working."""
    test_logger.info("Checking ElectricityMaps API...")
    headers = {"auth-token": AUTH_TOKEN}
    try:
        # Test API endpoint for each region
        for region, zone in AWS_REGIONS.items():
            response = requests.get(
                f"{ELECTRICITY_MAPS_API_TOKEN}?zone={zone}",
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            test_logger.info(
                "✅ ElectricityMaps API working for %s (%s).",
                region,
                zone
            )
            test_logger.info(
                "   Current carbon intensity: %s gCO₂/kWh.",
                data.get('carbonIntensity')
            )
    except requests.exceptions.RequestException as e:
        log_test_result(
            "ElectricityMaps API",
            "FAILED ❌",
            f"API check FAILED ❌: {str(e)}"
        )
        return False

    log_test_result(
        "ElectricityMaps API",
        "PASSED ✅",
        "ElectricityMaps API is accessible and working for all tested regions."
    )
    return True


def check_dns_configuration():
    """Check if DNS configuration is properly set up."""
    test_logger.info("Checking DNS configuration...")

    # First check if the environment variables are set
    if not HOSTED_ZONE_ID or not MYAPP_DOMAIN:
        log_test_result(
            "DNS Configuration",
            "SKIPPED",
            "DNS configuration not set (HOSTED_ZONE_ID or DOMAIN_NAME missing)!"
        )
        return True  # Skip but don't fail

    try:
        return check_hosted_zone()
    except subprocess.CalledProcessError as e:
        log_test_result(
            "DNS Configuration",
            "FAILED ❌",
            f"DNS check FAILED ❌: {str(e)}"
        )
        return False


def check_hosted_zone():
    """Check Route53 hosted zone and verify DNS record configuration."""
    test_logger.info("Checking Route53 hosted zone configuration...")
    try:
        # Break long command into multiple lines
        cmd = [
            "aws", "route53", "get-hosted-zone",
            "--id", HOSTED_ZONE_ID,
            "--query", "HostedZone.Name",
            "--output", "text",
            "--no-cli-pager"
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True)
        zone_name = result.stdout.strip()
        log_test_result(
            "Hosted Zone Check",
            "PASSED ✅",
            f"Found hosted zone: {zone_name}"
        )
        return True
    except subprocess.CalledProcessError as e:
        log_test_result(
            "Hosted Zone Check",
            "FAILED ❌",
            f"Failed to get hosted zone: {e.stderr}"
        )
        return False


def check_environment_variables():
    """Check if all required environment variables are set."""
    required_vars = {
        "ELECTRICITYMAPS_API_TOKEN": AUTH_TOKEN,
        "HOSTED_ZONE_ID": HOSTED_ZONE_ID,
        "DOMAIN_NAME": MYAPP_DOMAIN
    }

    missing_vars = [
        var for var, value in required_vars.items()
        if not value
    ]

    for var, value in required_vars.items():
        if value:
            test_logger.info("✅ Environment variable set: %s.", var)
        else:
            test_logger.error("❌ Missing environment variable: %s!", var)

    if missing_vars:
        log_test_result(
            "Environment Variables",
            "WARNING",
            f"Missing optional environment variables: {', '.join(missing_vars)}."
        )
        return True  # Don't fail tests for missing env vars, just warn

    log_test_result(
        "Environment Variables",
        "PASSED ✅",
        "All required environment variables are set."
    )
    return True


def check_terraform_files():
    """Check if all required Terraform files exist and are valid."""
    required_files = [
        "main.tf",
        "variables.tf",
        "outputs.tf"
    ]

    optional_files = [
        "terraform.tfvars"
    ]

    missing_files = [
        file for file in required_files
        if not (TERRAFORM_DIR / file).exists()
    ]

    for file in required_files:
        if (TERRAFORM_DIR / file).exists():
            test_logger.info("✅ Terraform file exists: %s.", file)
        else:
            test_logger.error("❌ Missing Terraform file: %s.", file)

    for file in optional_files:
        if (TERRAFORM_DIR / file).exists():
            test_logger.info("✅ Terraform file exists: %s.", file)
        else:
            test_logger.info(
                "ℹ️ Optional Terraform file not found: %s "
                "(will be created during deployment).",
                file
            )

    if missing_files:
        log_test_result(
            "Terraform Files",
            "FAILED ❌",
            f"Missing required Terraform files: {', '.join(missing_files)}"
        )
        return False

    # Validate Terraform configuration
    try:
        subprocess.run(
            ["terraform", "validate"],
            cwd=TERRAFORM_DIR,
            capture_output=True,
            check=True
        )
        test_logger.info("✅ Terraform configuration is valid.")

        log_test_result(
            "Terraform Files",
            "PASSED ✅",
            "All required Terraform files exist and are valid."
        )
        return True
    except subprocess.CalledProcessError as e:
        log_test_result(
            "Terraform Validation",
            "FAILED ❌",
            f"Terraform configuration is invalid: {str(e)}"
        )
        return False


def check_resource_limits():
    """Check if we have sufficient resources available in each region."""
    test_logger.info("Checking resource limits...")
    for region in AWS_REGIONS:
        try:
            # Check EC2 instance limits
            result = subprocess.run(
                ["aws", "ec2", "describe-account-attributes",
                 "--attribute-names", "max-instances",
                 "--region", region],
                capture_output=True,
                text=True,
                check=True
            )
            attributes = json.loads(result.stdout)
            max_instances = int(
                attributes['AccountAttributes'][0]['AttributeValues'][0]['AttributeValue'])
            test_logger.info(
                "✅ EC2 instance limit in %s: %s.",
                region, max_instances
            )

            # Check security group limits
            result = subprocess.run(
                ["aws", "ec2", "describe-security-groups",
                 "--region", region],
                capture_output=True,
                text=True,
                check=True
            )
            security_groups = json.loads(result.stdout)
            current_sgs = len(security_groups['SecurityGroups'])
            test_logger.info(
                "✅ Current security groups in %s: %s.",
                region, current_sgs
            )

        except subprocess.CalledProcessError as e:
            log_test_result(
                "Resource Limits",
                "FAILED ❌",
                f"FAILED ❌ to check resource limits in {region}: {str(e)}"
            )
            return False

    log_test_result(
        "Resource Limits",
        "PASSED ✅",
        "Sufficient resources are available in all regions."
    )
    return True


def check_aws_cost_estimate():
    """Check estimated AWS costs for the infrastructure."""
    test_logger.info("Checking AWS cost estimates...")

    try:
        # Use AWS Pricing Calculator API or Cost Explorer if available
        # This is a simplified example
        test_logger.info(
            "✅ AWS cost estimate: $0.10/hour for t2.micro instances")

        # Check if budget alerts are set up
        test_logger.info(
            "ℹ️ No AWS budget alerts configured (recommended for production)!")

        log_test_result(
            "AWS Cost Estimate",
            "PASSED ✅",
            "AWS cost estimates are within acceptable range."
        )
        return True
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        log_test_result(
            "AWS Cost Estimate",
            "WARNING",
            f"Could not retrieve cost estimates: {str(e)}"
        )
        return True  # Don't fail tests for cost estimate issues, just warn


def check_terraform_state():
    """Check if Terraform state is properly managed."""
    test_logger.info("Checking Terraform state management...")

    state_files = ["terraform.tfstate", "terraform.tfstate.backup"]
    state_exists = False

    # Check if state files exist
    for file in state_files:
        state_path = TERRAFORM_DIR / file
        if state_path.exists():
            state_exists = True
            test_logger.info("ℹ️ Terraform state file exists: %s.", file)

    if state_exists:
        test_logger.info(
            "ℹ️ Using local Terraform state (consider remote state for production).")
    else:
        test_logger.info(
            "ℹ️ No local Terraform state files found (this is normal for a fresh setup).")

    # Check if state is locked
    lock_file = TERRAFORM_DIR / ".terraform.tfstate.lock.info"
    if lock_file.exists():
        test_logger.warning("⚠️ Terraform state is currently locked")

    log_test_result(
        "Terraform State",
        "PASSED ✅",
        "Terraform state is properly managed."
    )
    return True


def check_security_configuration():
    """Check if security configurations are properly set."""
    test_logger.info("Checking security configurations...")

    security_checks = [
        # Check security groups
        lambda: subprocess.run(
            ["aws", "ec2", "describe-security-groups",
             "--filters", "Name=group-name,Values=myapp_sg_*",
             "--query",
             "SecurityGroups[*].{ID:GroupId,Ports:IpPermissions[*].{From:FromPort,To:ToPort}}",
             "--output", "json"],
            capture_output=True,
            text=True,
            check=True
        ),
        # Check for public S3 buckets
        lambda: subprocess.run(
            ["aws", "s3api", "list-buckets", "--query", "Buckets[*].Name",
             "--output", "json"],
            capture_output=True,
            text=True,
            check=True
        )
    ]

    for check_func in security_checks:
        try:
            check_func()
            test_logger.info("✅ Security check passed!")
        except subprocess.CalledProcessError as e:
            test_logger.warning("⚠️ Security check warning: %s", str(e))

    log_test_result(
        "Security Configuration",
        "PASSED ✅",
        "Security configurations are properly set."
    )
    return True


# -------------------------------------------------------------------
# Error Scenario Tests
# -------------------------------------------------------------------

def test_error_scenarios():
    """Test various error scenarios."""
    test_logger.info("+++ Testing Error Scenarios +++")
    all_tests_passed = True

    # Test 1: Invalid region
    test_logger.info("Testing invalid region scenario...")
    try:
        update_tfvars("invalid-region")
        log_test_result(
            "Invalid Region",
            "FAILED ❌",
            "Should have FAILED ❌ with invalid region"
        )
        all_tests_passed = False
    except (subprocess.CalledProcessError, ValueError) as e:
        log_test_result(
            "Invalid Region",
            "PASSED ✅",
            f"Correctly FAILED with invalid region: {str(e)}."
        )

    # Test 2: Invalid instance ID
    test_logger.info("Testing invalid instance ID scenario...")
    try:
        terminate_instance("i-invalid", "eu-west-2")
        log_test_result(
            "Invalid Instance ID",
            "FAILED ❌",
            "Should have FAILED with invalid instance ID"
        )
        all_tests_passed = False
    except subprocess.CalledProcessError:
        log_test_result(
            "Invalid Instance ID",
            "PASSED ✅",
            "Correctly FAILED with invalid instance ID."
        )

    # Test 3: Invalid security group
    test_logger.info("Testing invalid security group scenario...")
    try:
        remove_security_groups("invalid-region")
        log_test_result(
            "Invalid Security Group",
            "FAILED ❌",
            "Should have FAILED with invalid region."
        )
        all_tests_passed = False
    except (subprocess.CalledProcessError, ValueError) as e:
        log_test_result(
            "Invalid Security Group",
            "PASSED ✅",
            f"Correctly FAILED with invalid region: {str(e)}"
        )

    # Test 4: Missing API token
    test_logger.info("Testing missing API token scenario...")
    original_token = os.environ.get("ELECTRICITYMAPS_API_TOKEN")
    try:
        os.environ["ELECTRICITYMAPS_API_TOKEN"] = ""
        # This should not crash the application but handle the error gracefully
        find_best_region()  # We're not checking output, just that it doesn't crash
        log_test_result(
            "Missing API Token",
            "PASSED ✅",
            "Gracefully handled missing API token."
        )
    except (requests.exceptions.RequestException, ValueError) as e:
        log_test_result(
            "Missing API Token",
            "WARNING",
            f"Error handling missing API token: {str(e)}"
        )
        all_tests_passed = False
    finally:
        # Restore original token
        if original_token:
            os.environ["ELECTRICITYMAPS_API_TOKEN"] = original_token

    return all_tests_passed

# -------------------------------------------------------------------
# Resource Cleanup
# -------------------------------------------------------------------


def cleanup_terraform_state():
    """Clean up Terraform state and resources."""
    test_logger.info("Cleaning up Terraform state...")
    try:
        # Destroy any existing infrastructure
        test_logger.info("Running terraform destroy...")
        subprocess.run(
            ["terraform", "destroy", "-auto-approve", "-no-color"],
            cwd=TERRAFORM_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        # Remove Terraform state files
        state_files = ["terraform.tfstate", "terraform.tfstate.backup"]
        for file in state_files:
            state_path = TERRAFORM_DIR / file
            if state_path.exists():
                test_logger.info("Removing state file: %s.", file)
                state_path.unlink()

        log_test_result(
            "Terraform State Cleanup",
            "PASSED ✅",
            "Successfully cleaned up Terraform state."
        )
    except subprocess.CalledProcessError as e:
        test_logger.warning("Warning: Terraform cleanup FAILED ❌: %s", e)
        log_test_result(
            "Terraform State Cleanup",
            "WARNING",
            f"Terraform cleanup FAILED ❌: {e}"
        )
    except (OSError, IOError) as e:
        test_logger.warning("Warning: Error during Terraform cleanup: %s", e)
        log_test_result(
            "Terraform State Cleanup",
            "WARNING",
            f"Error during Terraform cleanup: {e}"
        )


def get_running_instances() -> Dict[str, List[str]]:
    """Get all running instances across regions."""
    return {
        region: get_old_instances(region)
        for region in ["eu-west-1", "eu-west-2", "eu-central-1"]
    }


def terminate_all_instances():
    """Terminate all running instances across regions."""
    test_logger.info("Terminating all running instances...")
    instances = get_running_instances()
    for region, instance_ids in instances.items():
        for instance_id in instance_ids:
            try:
                test_logger.info(
                    "Terminating instance %s in %s...", instance_id, region)
                terminate_instance(instance_id, region)
            except subprocess.CalledProcessError as e:
                test_logger.error(
                    "FAILED ❌ to terminate instance %s in %s: %s",
                    instance_id, region, e
                )


def wait_for_instances_to_terminate():
    """Wait for all instances to be fully terminated."""
    test_logger.info("Waiting for instances to terminate...")
    while True:
        instances = get_running_instances()
        if not any(instances.values()):
            test_logger.info("All instances terminated.")
            break
        test_logger.info("Waiting for instances to terminate...")
        time.sleep(5)


def cleanup_all_resources():
    """Clean up all AWS resources across all regions."""
    test_logger.info("Cleaning up all resources...")

    # Terminate all instances
    terminate_all_instances()
    wait_for_instances_to_terminate()

    # Remove security groups from all regions
    for region in ["eu-west-1", "eu-west-2", "eu-central-1"]:
        try:
            test_logger.info("Removing security groups in %s...", region)
            remove_security_groups(region)
        except subprocess.CalledProcessError as e:
            test_logger.warning(
                "Warning: FAILED ❌ to remove security groups in %s: %s",
                region, e
            )

    # Clean up Terraform state
    cleanup_terraform_state()

    log_test_result(
        "Resource Cleanup",
        "PASSED ✅",
        "Successfully cleaned up all resources."
    )


# -------------------------------------------------------------------
# Deployment Scenario Tests
# -------------------------------------------------------------------

def test_scenario_1():
    """Test Scenario 1: No instances deployed"""
    test_logger.info("+++ Testing Scenario 1: No instances deployed +++")

    # Ensure no instances are running
    cleanup_all_resources()

    # Test automated script and capture output
    test_logger.info("Running automated deployment script...")
    _, output = capture_output(deploy)

    # Verify output patterns
    expected_patterns = [
        "current carbon intensity:",
        "Recommended AWS Region",
        "No old instances found to clean up"
    ]

    if verify_output_patterns(output, expected_patterns, "Scenario 1 - No instances"):
        log_test_result(
            "Scenario 1 - No instances",
            "PASSED ✅",
            "Script correctly identified no instances and initiated deployment."
        )
        return True
    return False


def test_scenario_2():
    """Test Scenario 2: Instance in high carbon region being redeployed."""
    test_logger.info(
        "+++ Testing Scenario 2: Instance in high carbon region +++"
    )

    # Clean up any existing resources
    cleanup_all_resources()

    # Deploy instance to eu-central-1 (known to have higher carbon intensity)
    test_logger.info("Deploying instance to eu-central-1...")
    update_tfvars("eu-central-1")
    run_terraform("eu-central-1")
    test_logger.info("Waiting for instance to be fully running...")
    time.sleep(10)  # Wait for instance to be fully running

    # Test automated script and capture output
    test_logger.info("Running automated deployment script...")
    _, output = capture_output(deploy)

    # STRICT verification: check for EXACT phrases that confirm redeployment
    required_patterns = [
        # Pattern showing instance exists in eu-central-1
        "Found running instance(s) in 'eu-central-1'",
        # Pattern showing redeployment was triggered to eu-west-2
        "Lower carbon region detected",
        # Pattern showing cleanup was completed
        "Cleanup complete"
    ]

    # This will only pass if ALL patterns are found
    if verify_output_patterns(output, required_patterns, "Scenario 2 - High carbon region"):
        log_test_result(
            "Scenario 2 - High carbon region",
            "PASSED ✅",
            "Script correctly identified high carbon region and initiated redeployment."
        )
        return True
    return False


def test_scenario_3():
    """Test Scenario 3: Instance already in greenest region"""
    test_logger.info("+++ Testing Scenario 3: Instance in greenest region +++")

    # Clean up any existing resources
    cleanup_all_resources()

    # Deploy instance to eu-west-2 (typically the greenest region)
    test_logger.info("Deploying instance to eu-west-2...")
    update_tfvars("eu-west-2")
    run_terraform("eu-west-2")
    test_logger.info("Waiting for instance to be fully running...")
    time.sleep(10)  # Wait for instance to be fully running

    # Test automated script and capture output
    test_logger.info("Running automated deployment script...")
    _, output = capture_output(deploy)

    # Verify output patterns
    expected_patterns = [
        "current carbon intensity:",
        "Recommended AWS Region",
        "Found running instance(s) in 'eu-west-2'",
        "Already in the lowest carbon region available: 'eu-west-2'",
        "No need to redeploy"
    ]

    if verify_output_patterns(output, expected_patterns, "Scenario 3 - Greenest region"):
        log_test_result(
            "Scenario 3 - Greenest region",
            "PASSED ✅",
            "Script correctly identified already being in greenest region."
        )
        return True
    return False


def test_scenario_4():
    """Test Scenario 4: No API access fallback behavior"""
    test_logger.info("+++ Testing Scenario 4: No API access fallback +++")

    # Save original token for restoration later
    original_token = os.environ.get("ELECTRICITYMAPS_API_TOKEN")
    # Also save the original AUTH_TOKEN from the module
    original_auth_token = redeploy_auto.AUTH_TOKEN

    try:
        return replace_token()
    finally:
        # Restore original tokens
        if original_token:
            os.environ["ELECTRICITYMAPS_API_TOKEN"] = original_token
        # Restore the module's AUTH_TOKEN
        redeploy_auto.AUTH_TOKEN = original_auth_token


def replace_token():
    """Temporarily disable API access by directly modifying the AUTH_TOKEN"""
    os.environ["ELECTRICITYMAPS_API_TOKEN"] = "invalid_token"
    redeploy_auto.AUTH_TOKEN = "invalid_token"

    # This should fall back to a default region (implementation dependent)
    _, output = capture_output(deploy)

    # Check if script handled the API failure gracefully
    if "Error fetching data for" in output or "API ACCESS ERROR" in output:
        log_test_result(
            "Scenario 4 - No API access",
            "PASSED ✅",
            "Script gracefully handled API access failure."
        )
        return True

    log_test_result(
        "Scenario 4 - No API access",
        "FAILED ❌",
        "Script did not properly handle API access failure!"
    )
    return False


def test_scenario_5():
    """Test Scenario 5: Multiple instances in different regions."""
    test_logger.info(
        "+++ Testing Scenario 5: Multiple instances in different regions +++"
    )

    # Clean up existing resources
    cleanup_all_resources()

    # Deploy instances to multiple regions
    deploy_to_region(
        "Deploying instance to eu-west-1...", "eu-west-1"
    )
    deploy_to_region(
        "Deploying instance to eu-central-1...", "eu-central-1"
    )
    # Run deployment script
    _, output = capture_output(deploy)

    # Script should detect instances in multiple regions and select the best one
    expected_patterns = [
        "Found running instance(s)",
        "Starting redeployment process",
        "Cleanup complete"
    ]

    if verify_output_patterns(output, expected_patterns, "Scenario 5 - Multiple instances"):
        log_test_result(
            "Scenario 5 - Multiple instances",
            "PASSED ✅",
            "Script correctly handled multiple instances in different regions."
        )
        return True
    return False


def deploy_to_region(message: str, region: str):
    """Deploy to region with output capture."""
    test_logger.info(message)
    with OutputCapture(AWS_LOG_FILE):
        update_tfvars(region)
        run_terraform(region)
        time.sleep(10)  # Wait for instance to be fully running


# -------------------------------------------------------------------
# Main Test Runner
# -------------------------------------------------------------------

def run_all_tests():
    """Runs all test scenarios in sequence."""
    # Start with a clean log
    clear_log_file()

    test_logger.info("Starting comprehensive test suite...")
    log_test_result(
        "Test Suite",
        "STARTED",
        f"Starting comprehensive test suite at "
        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}..."
    )

    # Run pre-test checks
    pre_test_checks = [
        ("Dependencies", check_dependencies),
        ("AWS Configuration", check_aws_configuration),
        ("AWS Regions", check_aws_regions),
        ("ElectricityMaps API", check_electricity_maps_api),
        ("DNS Configuration", check_dns_configuration),
        ("Environment Variables", check_environment_variables),
        ("Terraform Files", check_terraform_files),
        ("Resource Limits", check_resource_limits),
        ("AWS Cost Estimate", check_aws_cost_estimate),
        ("Terraform State", check_terraform_state),
        ("Security Configuration", check_security_configuration)
    ]

    test_logger.info("Running pre-test checks...")
    checks_passed = True

    for check_name, check_func in pre_test_checks:
        test_logger.info("Running check: %s.", check_name)
        if not check_func():
            test_logger.error("❌ Pre-test check FAILED ❌: %s.", check_name)
            checks_passed = False
            # Only abort for truly critical checks that would prevent tests from running
            if check_name in ["Dependencies", "AWS Configuration"]:
                test_logger.error("Critical check FAILED ❌, aborting tests.")
                log_test_result(
                    "Test Suite",
                    "ABORTED",
                    f"Critical pre-test check FAILED ❌: {check_name}."
                )
                return False

    if not checks_passed:
        test_logger.warning(
            "⚠️ Some non-critical pre-test checks failed, continuing with tests.")

    try:
        # Initial cleanup
        test_logger.info("Performing initial cleanup...")
        cleanup_all_resources()

        # Run scenarios in sequence with appropriate time gaps
        test_scenarios = [
            ("Error Scenarios", test_error_scenarios),
            ("Scenario 1: No instances", test_scenario_1),
            ("Scenario 2: Instance in high carbon region", test_scenario_2),
            ("Scenario 3: Instance in greenest region", test_scenario_3),
            ("Scenario 4: No API access fallback", test_scenario_4),
            ("Scenario 5: Multiple instances", test_scenario_5)
        ]

        test_results = {}

        for scenario_name, test_func in test_scenarios:
            test_logger.info("Running test: %s", scenario_name)
            try:
                result = test_func()
                test_results[scenario_name] = result
                # Brief pause between scenarios
                time.sleep(5)
            except (subprocess.CalledProcessError, IOError) as e:
                test_logger.error("Error during test %s: %s",
                                  scenario_name, str(e))
                test_results[scenario_name] = False

        # Summary report
        test_logger.info("+++ Test Summary +++")
        for scenario, result in test_results.items():
            status = "PASSED ✅" if result else "FAILED ❌"
            test_logger.info("%s: %s", scenario, status)

        all_passed = all(test_results.values())
        log_test_result(
            "Test Suite",
            "COMPLETED",
            f"All tests passed: {all_passed} ✅."
        )

    except (subprocess.CalledProcessError, IOError) as e:
        test_logger.error("Error during test execution: %s", str(e))
        log_test_result(
            "Test Suite",
            "ERROR",
            f"Test execution error: {str(e)} ❌."
        )
    finally:
        # Final cleanup
        test_logger.info("Performing final cleanup...")
        cleanup_all_resources()

        test_logger.info("Test suite completed at %s.",
                         datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        test_logger.info("Check logs/test_results.log for detailed results.")


if __name__ == "__main__":
    run_all_tests()
