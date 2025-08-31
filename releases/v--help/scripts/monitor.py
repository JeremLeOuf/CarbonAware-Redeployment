#!/usr/bin/env python3
"""
Standalone monitoring script - can be run via cron job
"""
import boto3
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()


def check_deployment_health():
    """Check health of deployed instances"""
    ec2 = boto3.client('ec2')

    # Get running instances with your tag
    response = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Project', 'Values': ['CarbonAware']},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )

    health_status = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            public_ip = instance.get('PublicIpAddress')
            if public_ip:
                try:
                    resp = requests.get(
                        f'http://{public_ip}/health', timeout=5)
                    health_status.append({
                        'instance_id': instance['InstanceId'],
                        'region': instance['Placement']['AvailabilityZone'],
                        'status': 'healthy' if resp.status_code == 200 else 'unhealthy',
                        'carbon_intensity': resp.json().get('carbon_intensity', 'unknown')
                    })
                except:
                    health_status.append({
                        'instance_id': instance['InstanceId'],
                        'status': 'unreachable'
                    })

    return health_status


def send_alert(message):
    """Send email alert for critical issues"""
    if not os.getenv('ALERT_EMAIL'):
        return

    msg = MIMEText(message)
    msg['Subject'] = 'CarbonAware Deployment Alert'
    msg['From'] = os.getenv('SMTP_FROM')
    msg['To'] = os.getenv('ALERT_EMAIL')

    # Send email (configure SMTP settings in .env)
    # Implementation depends on your email provider


if __name__ == "__main__":
    health = check_deployment_health()

    # Check for issues
    unhealthy = [h for h in health if h['status'] != 'healthy']
    if unhealthy:
        send_alert(f"Unhealthy instances detected: {unhealthy}")

    # Log status
    with open('logs/monitoring.log', 'a') as f:
        f.write(f"{datetime.now().isoformat()} - {health}\n")
