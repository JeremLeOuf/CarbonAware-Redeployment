"""
Environment configuration management for CarbonAware deployment system.

This module provides centralized configuration management for different deployment
environments (dev, staging, production). It defines environment-specific settings
including instance types, AWS regions, carbon thresholds, and operational parameters.

The EnvironmentConfig class provides a clean interface for accessing environment-
specific configurations with fallback mechanisms for missing environments.
"""

# config/environments.py
import os
from typing import Dict


class EnvironmentConfig:
    """Manage deployment configurations per environment"""

    ENVIRONMENTS = {
        'dev': {
            'instance_type': 't2.micro',
            'regions': ['us-east-1', 'us-west-2'],
            'carbon_threshold': 100,  # gCO2/kWh
            'health_check_timeout': 60,
            'dns_ttl': 60
        },
        'staging': {
            'instance_type': 't3.small',
            'regions': ['us-east-1', 'eu-west-1', 'ap-southeast-1'],
            'carbon_threshold': 75,
            'health_check_timeout': 120,
            'dns_ttl': 300
        },
        'production': {
            'instance_type': 't3.medium',
            'regions': ['us-east-1', 'eu-west-1', 'ap-southeast-1', 'us-west-2'],
            'carbon_threshold': 50,
            'health_check_timeout': 180,
            'dns_ttl': 60
        }
    }

    @classmethod
    def get_config(cls, env: str = None) -> Dict:
        """
        Get configuration for a specific environment.

        Args:
            env (str, optional): Environment name. Defaults to None.
                If None, uses DEPLOY_ENV environment variable or 'dev'.

        Returns:
            Dict: Configuration dictionary for the specified environment.
                Falls back to 'dev' configuration if environment not found.
        """
        env = env or os.getenv('DEPLOY_ENV', 'dev')
        return cls.ENVIRONMENTS.get(env, cls.ENVIRONMENTS['dev'])
