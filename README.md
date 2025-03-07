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
pip install python-dotenv requests
```

or use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
pip install python-dotenv requests
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
- If “yes”, it updates terraform.tfvars and applies Terraform.
- After creation, it checks HTTP availability on port 80.

6. Get the public IP:

- The script prints the new instance’s IP or you can run:

```bash
terraform output -raw instance_public_ip
```

Visit http://<instance_public_ip> to see your Dockerized Flask app.
