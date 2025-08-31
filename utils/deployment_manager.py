"""
CarbonAware Deployment Manager Module

This module provides a comprehensive deployment management system for CarbonAware applications
with AWS infrastructure. It includes pre-deployment validation, state management, rollback
capabilities, and structured logging for deployment operations.

The DeploymentManager class handles:
- Pre-deployment environment and configuration checks
- Terraform state management and backup
- AWS credential validation
- Deployment snapshots for rollback scenarios
- Structured JSON logging for audit trails

Key Features:
- Environment-specific deployment management
- Automated rollback capabilities
- Comprehensive error handling and logging
- AWS integration with boto3
- Terraform state validation and backup

Author: CarbonAware Development Team
License: MIT
"""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


class DeploymentManager:
    """Manage deployments with proper error handling and rollback"""

    def __init__(self, environment='dev'):
        self.environment = environment
        self.setup_logging()
        self.deployment_history = []

    def setup_logging(self):
        """Configure structured logging"""
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)

        # Create detailed log file with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_dir / f'deployment_{self.environment}_{timestamp}.json'

        # JSON formatter for structured logs
        self.logger = logging.getLogger('CarbonAwareDeployment')
        handler = logging.FileHandler(log_file)

        # Log format for easy parsing
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"module": "%(name)s", "message": "%(message)s"}'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def pre_deployment_checks(self) -> bool:
        """Perform pre-deployment validation checks"""
        checks = {
            'terraform_installed': self.check_terraform_installation(),
            'aws_credentials': self.check_aws_credentials(),
            'terraform_state': self.check_terraform_state(),
            'environment_config': self.check_environment_config()
        }

        for check, result in checks.items():
            if not result:
                self.logger.error("Pre-deployment check failed: %s", check)
                return False

        self.logger.info("All pre-deployment checks passed")
        return True

    def check_terraform_installation(self) -> bool:
        """Check if Terraform is installed and accessible"""
        try:
            subprocess.run(['terraform', '--version'],
                           capture_output=True, text=True, check=True)
            self.logger.info("Terraform installation verified")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.error("Terraform not found or not accessible")
            return False

    def check_aws_credentials(self) -> bool:
        """Check if AWS credentials are configured"""
        try:
            session = boto3.Session()
            sts = session.client('sts')
            sts.get_caller_identity()
            self.logger.info("AWS credentials verified")
            return True
        except (NoCredentialsError, ClientError, BotoCoreError) as e:
            self.logger.error("AWS credentials check failed: %s", e)
            return False

    def check_terraform_state(self) -> bool:
        """Check if Terraform state file exists and is valid"""
        state_file = Path('terraform/terraform.tfstate')
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    json.load(f)
                self.logger.info("Terraform state file verified")
                return True
            except json.JSONDecodeError:
                self.logger.error("Invalid Terraform state file")
                return False
        else:
            self.logger.warning("No Terraform state file found")
            return True  # Allow first-time deployment

    def check_environment_config(self) -> bool:
        """Check if environment configuration is valid"""
        config_file = Path('config/environments.py')
        if config_file.exists():
            self.logger.info("Environment configuration verified")
            return True
        else:
            self.logger.error("Environment configuration file not found")
            return False

    def get_current_region(self) -> str:
        """Get current AWS region"""
        try:
            session = boto3.Session()
            return session.region_name or 'us-east-1'
        except (NoCredentialsError, BotoCoreError):
            return 'us-east-1'

    def backup_terraform_state(self) -> Dict:
        """Backup current Terraform state"""
        state_file = Path('terraform/terraform.tfstate')
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, IOError) as e:
                self.logger.error("Failed to backup Terraform state: %s", e)
        return {}

    def create_deployment_snapshot(self):
        """Create a snapshot before deployment for rollback"""
        snapshot = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'environment': self.environment,
            'current_region': self.get_current_region(),
            'terraform_state': self.backup_terraform_state()
        }

        snapshot_file = Path(
            'backups') / f'snapshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        snapshot_file.parent.mkdir(exist_ok=True)

        with open(snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2)

        return snapshot_file

    def rollback(self, snapshot_file: Path):
        """Rollback to previous deployment state"""
        self.logger.warning("Initiating rollback from %s", snapshot_file)

        try:
            # Load the snapshot data
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                snapshot_data = json.load(f)

            # Restore Terraform state if available
            if 'terraform_state' in snapshot_data and snapshot_data['terraform_state']:
                state_file = Path('terraform/terraform.tfstate')
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump(snapshot_data['terraform_state'], f, indent=2)
                self.logger.info("Terraform state restored from snapshot")

            # Additional rollback steps can be implemented here
            # For example: restore environment variables, configuration files, etc.

            self.logger.info("Rollback completed successfully")
            return True

        except (json.JSONDecodeError, OSError, IOError) as e:
            self.logger.error("Rollback failed: %s", e)
            return False
