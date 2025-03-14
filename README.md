# MyApp Terraform Deployment

This repository contains:

- **Terraform** configurations for deploying a Dockerized Flask app on AWS EC2.
- A Python script (`redeploy.py`) that:
  1. Checks carbon intensity via Electricity Maps.
  2. Chooses the greenest AWS region.
  3. Updates `terraform.tfvars`.
  4. Runs Terraform to deploy or redeploy the EC2 instance.

## Prerequisites

1. **AWS CLI** installed and configured with credentials.
2. **Terraform** installed (>= 1.0).
3. **Python 3** and `pip` for installing dependencies.

## Setup Instructions

1. **Clone** this repository:

```bash
git clone https://github.com/YourUsername/myapp-terraform.git
cd myapp-terraform
```

2. **Install** Python dependencies:

```bash
pip install -r requirements.txt
```

or use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file (not committed) to store environment variables:

```bash
# .env example
ELECTRICITYMAPS_API_TOKEN="YOUR_API_TOKEN"
HOSTED_ZONE_ID="YOUR_ROUTE53_ZONE_ID"
DOMAIN_NAME="myapp.example.com"
DNS_TTL="60"
```

You can also export them as environment variables if you prefer.

4. Initialize Terraform (the first time):

```bash
cd terraform
terraform init
cd ..
```

5. Run the Redeploy script:

```bash
python redeploy.py
```

- It will ask if you want to deploy to the recommended region.
- If “yes”, it updates `terraform.tfvars` and applies Terraform.
- After creation, it checks HTTP availability on port 80.

6. Get the public IP:

- The script prints the new instance’s IP or you can run:

```bash
terraform output -raw instance_public_ip
```

Visit http://<instance_public_ip> to see your Dockerized Flask app.

## Deployment Details

- The application is deployed using Terraform modules for networking and compute resources.
- Security groups are created dynamically to allow HTTP traffic.
- The deployment script automatically handles instance termination and cleanup of old resources.

## Logging

- Logs for the deployment process are stored in the `logs` directory.
- Test results and AWS interactions are logged for debugging and monitoring purposes.

## Notes

- Ensure that your AWS credentials have the necessary permissions to create and manage EC2 instances, security groups, and Route53 records.
- The application is designed to be carbon-aware, selecting the AWS region with the lowest carbon intensity for deployment.
- The deployment process includes a health check to ensure the application is running correctly after deployment.

## Testing

- A comprehensive test suite is available in `full_test_suite.py` to simulate different deployment scenarios and verify the behavior of the redeploy scripts.
- Ensure all dependencies are installed before running the tests.

## Contributing

Feel free to submit issues or pull requests for improvements or bug fixes.