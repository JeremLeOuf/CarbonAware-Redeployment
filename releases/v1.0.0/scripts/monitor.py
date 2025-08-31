#!/usr/bin/env python3
"""
Standalone monitoring script - can be run via cron job
"""
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

import boto3
import requests
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
            if public_ip := instance.get('PublicIpAddress'):
                try:
                    resp = requests.get(
                        f'http://{public_ip}/health', timeout=5)
                    health_status.append({
                        'instance_id': instance['InstanceId'],
                        'region': instance['Placement']['AvailabilityZone'],
                        'status': 'healthy' if resp.status_code == 200 else 'unhealthy',
                        'carbon_intensity': resp.json().get('carbon_intensity', 'unknown')
                    })
                except (requests.RequestException, requests.Timeout,
                        requests.ConnectionError, ValueError) as e:
                    health_status.append({
                        'instance_id': instance['InstanceId'],
                        'status': 'unreachable',
                        'error': str(e)
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

    try:
        send_email_via_smtp(msg)
    except (smtplib.SMTPException, OSError, ConnectionError) as e:
        print(f"Failed to send alert email: {e}")


def send_email_via_smtp(msg):
    """Send email message via SMTP server.

    Args:
        msg: MIMEText message object to be sent

    Raises:
        smtplib.SMTPException: If SMTP operation fails
        OSError: If connection to SMTP server fails
        ConnectionError: If network connection fails
    """
    # Configure SMTP settings from environment variables
    smtp_server = os.getenv('SMTP_SERVER', 'localhost')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_username = os.getenv('SMTP_USERNAME')
    smtp_password = os.getenv('SMTP_PASSWORD')

    # Create SMTP connection
    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()  # Enable TLS encryption

    # Authenticate if credentials are provided
    if smtp_username and smtp_password:
        server.login(smtp_username, smtp_password)

    # Send the email
    server.send_message(msg)
    server.quit()

    print(f"Alert email sent to {os.getenv('ALERT_EMAIL')}")


if __name__ == "__main__":
    health = check_deployment_health()

    if unhealthy := [h for h in health if h['status'] != 'healthy']:
        send_alert(f"Unhealthy instances detected: {unhealthy}")

    # Log status
    with open('logs/monitoring.log', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().isoformat()} - {health}\n")
