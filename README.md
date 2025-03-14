# MyApp Terraform Deployment

This repository provides a streamlined, automated solution for deploying a Dockerized Flask application to AWS EC2 instances using Terraform. The deployment is carbon-aware, selecting AWS regions based on their carbon intensity.

---

## Features

- **Terraform Configurations**: Automated deployment of Flask applications onto AWS EC2 instances.
- **Carbon-Aware Deployment**: Python scripts interact with Electricity Maps API to identify the AWS region with the lowest carbon intensity.
- **Dynamic Updates**: Automatically updates `terraform.tfvars` to reflect region selections.
- **Automated Deployment and Redeployment**: Deploy new infrastructure seamlessly or redeploy existing infrastructure based on carbon metrics.

---

## Project Structure

```
CarbonAware-Redeployment/
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── modules/
│   │   ├── compute/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   └── networking/
│   │       ├── main.tf
│   │       └── outputs.tf
├── scripts/
│   └── userdata.sh
├── redeploy_interactive.py
├── redeploy_auto.py
├── full_test_suite.py
├── requirements.txt
├── logs/
└── README.md
```

*Note:* The `venv/` directory and `.env` files are intentionally excluded from version control.

---

## Prerequisites

Ensure the following are installed and correctly configured:

- **AWS CLI (v2+)**: [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  - Configure AWS CLI with proper permissions:

    ```bash
    aws configure
    ```
  
- **Terraform (v1.0+)**: [Terraform Downloads](https://www.terraform.io/downloads)
  - Verify installation:

    ```bash
    terraform -version
    ```

- **Python 3.8+ and pip**:
  - Verify installation:

    ```bash
    python3 --version
    pip --version
    ```

---

## Setup Instructions

### 1. Clone Repository

```bash
git clone https://github.com/YourUsername/myapp-terraform.git
cd myapp-terraform
```

### 2. Set Up Virtual Environment

Create and activate your Python virtual environment:

```bash
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root to store sensitive credentials:

```bash
touch .env
```

Populate `.env` with your details:

```ini
ELECTRICITYMAPS_API_TOKEN="YOUR_API_TOKEN"
HOSTED_ZONE_ID="YOUR_ROUTE53_ZONE_ID"
DOMAIN_NAME="myapp.example.com"
DNS_TTL="60"
```

Alternatively, export these as environment variables directly.

### 4. Initialize Terraform

Navigate into the Terraform directory and initialize:

```bash
cd terraform
terraform init
cd ..
```

### 5. Run Test Suite

Before deploying, ensure your scripts and Terraform configurations are working correctly:

```bash
python3 full_test_suite.py
```

Verify all tests pass before proceeding to deployment.

---

## Deploying the Application

Run the interactive deployment script to select the optimal region based on carbon intensity:

```bash
python3 redeploy_interactive.py
```

- The script recommends the AWS region with the lowest carbon intensity.
- Confirm to automatically update `terraform.tfvars` and deploy.
- A health check verifies HTTP availability on port 80 after deployment.

### Accessing Your Application

Obtain your new instance's public IP:

```bash
terraform output -raw instance_public_ip
```

Visit `http://<instance_public_ip>` in your web browser to access your Flask app.

---

## Deployment Details

- Modular Terraform deployment architecture for compute and networking.
- Automatic security group configuration for HTTP traffic.
- Built-in cleanup of older EC2 instances and associated resources upon redeployment.

## Logging

- All deployment processes, AWS interactions, and test outcomes are logged under the `logs` directory for debugging and monitoring.

## Notes

- AWS credentials require permissions to manage EC2, security groups, and Route53.
- Deployments prioritize carbon efficiency by selecting regions based on real-time carbon intensity.
- Post-deployment health checks ensure application availability and functionality.

---

## Testing

- Comprehensive testing via `full_test_suite.py` ensures reliability.
- Simulates diverse deployment scenarios to pinpoint potential issues.

---

## Contributing

Contributions, improvements, and bug fixes are welcome. Submit pull requests or raise issues to collaborate.

---

🌱 **Deploy sustainably, automate confidently, and contribute proactively!**
