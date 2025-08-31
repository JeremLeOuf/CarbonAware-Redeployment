# 🌱 CarbonAware-Redeployment

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Terraform 1.0+](https://img.shields.io/badge/terraform-1.0+-purple.svg)](https://www.terraform.io/)
[![AWS](https://img.shields.io/badge/AWS-EC2-orange.svg)](https://aws.amazon.com/ec2/)

An automated, carbon-aware cloud deployment framework that dynamically deploys Dockerized applications to AWS EC2 instances, prioritizing regions with the lowest carbon intensity for sustainable cloud computing.

## 🎯 Key Features

- **🌍 Carbon-Aware Optimization**: Real-time region selection based on carbon intensity data from Electricity Maps API
- **⚡ Zero-Downtime Migrations**: Seamless infrastructure transitions between regions
- **🔄 Automated Redeployment**: Continuous monitoring and automatic migration to greener regions
- **🏗️ Infrastructure as Code**: Complete Terraform automation for AWS resources
- **📊 Comprehensive Monitoring**: Built-in health checks, logging, and deployment tracking
- **🐳 Docker Support**: Fully containerized deployment option
- **🛡️ Production-Ready**: Error handling, rollback capabilities, and state management

## 📋 Table of Contents

- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Deployment Modes](#-deployment-modes)
- [Monitoring](#-monitoring)
- [Release Management](#-release-management)
- [Testing](#-testing)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

## 🏗️ Architecture

```
CarbonAware-Redeployment/
├── terraform/                    # Infrastructure as Code
│   ├── main.tf                  # Main Terraform configuration
│   ├── variables.tf             # Variable definitions
│   ├── outputs.tf               # Output definitions
│   ├── backend.tf               # State management configuration
│   ├── modules/                 # Reusable Terraform modules
│   │   ├── compute/            # EC2 instance management
│   │   └── networking/         # VPC and security groups
├── scripts/                     # Automation scripts
│   ├── setup.sh                # One-command setup script
│   ├── userdata.sh            # EC2 initialization script
│   ├── create-release-package.py  # Release packaging
│   ├── setup-terraform-backend.sh # Backend initialization
│   └── setup-cron.sh          # Cron job configuration
├── config/                      # Configuration management
│   ├── environments.py         # Environment-specific configs
│   └── .env.template          # Environment variables template
├── utils/                       # Utility modules
│   └── deployment_manager.py  # Deployment orchestration
├── redeploy_interactive.py     # Interactive deployment mode
├── redeploy_auto.py           # Automated deployment mode
├── monitor.py                  # Standalone monitoring script
├── full_test_suite.py         # Comprehensive testing suite
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container configuration
├── Makefile                    # Simplified operations
├── logs/                       # Deployment and monitoring logs
└── README.md                   # This file

```

## ✅ Prerequisites

### Required Software

| Component | Version | Installation Guide |
|-----------|---------|-------------------|
| **AWS CLI** | v2+ | [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **Terraform** | v1.0+ | [Download Page](https://www.terraform.io/downloads) |
| **Python** | 3.8+ | [Python.org](https://www.python.org/downloads/) |
| **Docker** | 20.10+ (optional) | [Get Docker](https://docs.docker.com/get-docker/) |

### AWS Permissions

Ensure your AWS IAM user has the following permissions:

- EC2: Full access for instance management
- VPC: Network and security group management
- Route53: DNS record management (if using custom domain)
- S3: For Terraform state storage
- DynamoDB: For state locking

## 🚀 Quick Start

Get up and running in under 5 minutes:

```bash
# 1. Clone the repository
git clone https://github.com/JeremLeOuf/CarbonAware-Redeployment.git
cd CarbonAware-Redeployment

# 2. Run automated setup
make setup

# 3. Configure environment variables
cp .env.template .env
nano .env  # Add your API tokens

# 4. Deploy to development
make deploy-dev
```

## 📦 Installation

### Automated Setup

The easiest way to get started:

```bash
bash scripts/setup.sh
```

This script will:

- ✅ Verify all prerequisites
- ✅ Create Python virtual environment
- ✅ Install dependencies
- ✅ Initialize Terraform
- ✅ Set up configuration templates

### Manual Setup

For more control over the installation:

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure AWS CLI
aws configure

# 4. Initialize Terraform backend
bash scripts/setup-terraform-backend.sh

# 5. Initialize Terraform
cd terraform
terraform init
cd ..

# 6. Set up environment variables
cp .env.template .env
```

### Docker Setup

For containerized deployment:

```bash
# Build the Docker image
docker build -t carbon-aware:latest .

# Run with environment variables
docker run --env-file .env carbon-aware:latest redeploy_interactive.py
```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file with the following variables:

```bash
# API Configuration
ELECTRICITYMAPS_API_TOKEN="your_api_token_here"

# AWS Configuration (optional, can use AWS CLI defaults)
AWS_REGION="us-east-1"
AWS_PROFILE="default"

# DNS Configuration (optional)
HOSTED_ZONE_ID="your_route53_zone_id"
DOMAIN_NAME="myapp.example.com"
DNS_TTL="60"

# Deployment Configuration
DEPLOY_ENV="dev"  # dev, staging, or production
CARBON_THRESHOLD="50"  # Maximum acceptable gCO2/kWh

# Monitoring (optional)
ALERT_EMAIL="your-email@example.com"
SMTP_FROM="alerts@example.com"
```

### Environment-Specific Configurations

Configure different settings per environment in `config/environments.py`:

```python
'production': {
    'instance_type': 't3.medium',
    'regions': ['us-east-1', 'eu-west-1', 'ap-southeast-1'],
    'carbon_threshold': 50,  # gCO2/kWh
    'health_check_timeout': 180,
    'dns_ttl': 60
}
```

## 🎮 Usage

### Interactive Deployment

For manual control over region selection:

```bash
python3 redeploy_interactive.py
```

This will:

1. Fetch current carbon intensity for all configured regions
2. Display recommendations based on carbon data
3. Allow you to select the deployment region
4. Deploy infrastructure and application
5. Run health checks

### Automated Deployment

For hands-off operation:

```bash
python3 redeploy_auto.py
```

The system will automatically select the region with the lowest carbon intensity.

### Using Makefile Commands

```bash
# View all available commands
make help

# Validate code and configuration
make validate

# Run tests
make test

# Deploy to different environments
make deploy-dev
make deploy-staging
make deploy-prod

# Create release package
make package VERSION=1.2.0

# Clean temporary files
make clean
```

## 🔄 Deployment Modes

### Development Mode

- Uses `t2.micro` instances (AWS free tier eligible)
- Limited to 2 regions for testing
- Higher carbon threshold (100 gCO2/kWh)
- Verbose logging enabled

### Staging Mode

- Uses `t3.small` instances
- Tests across 3 regions
- Moderate carbon threshold (75 gCO2/kWh)
- Standard logging

### Production Mode

- Uses `t3.medium` instances or higher
- Deploys across all available regions
- Strict carbon threshold (50 gCO2/kWh)
- Enhanced monitoring and alerting

## 📊 Monitoring

### Real-Time Health Checks

Monitor deployment health:

```bash
python3 monitor.py
```

Output includes:

- Instance status
- Current region
- Carbon intensity
- Application health

### Automated Monitoring

Set up continuous monitoring with cron:

```bash
bash scripts/setup-cron.sh
```

This configures:

- Health checks every 5 minutes
- Carbon intensity checks hourly
- Daily state backups

### Viewing Logs

```bash
# View latest deployment log
tail -f logs/deployment_*.json

# View monitoring history
cat logs/monitoring.log

# Parse JSON logs with jq
cat logs/deployment_*.json | jq '.message'
```

## 📦 Release Management

### Creating a Release

Generate a complete release package:

```bash
python3 scripts/create-release-package.py 1.2.0
```

This creates:

- Versioned release directory
- Compressed archive (`carbon-aware-v1.2.0.tar.gz`)
- Manifest with checksums
- Deployment instructions

### Release Contents

Each release includes:

- All Terraform modules
- Python scripts and requirements
- Configuration templates
- Documentation
- Deployment manifest with checksums

### Deploying a Release

```bash
# Extract release
tar -xzf carbon-aware-v1.2.0.tar.gz
cd carbon-aware-v1.2.0

# Follow included deployment steps
cat manifest.json | jq '.deployment_steps'
```

## 🧪 Testing

### Run Full Test Suite

```bash
python3 full_test_suite.py
```

Tests include:

- ✅ AWS connectivity
- ✅ Terraform validation
- ✅ API token verification
- ✅ Regional availability
- ✅ Carbon data retrieval
- ✅ Deployment simulation

### Individual Test Categories

```bash
# Test AWS configuration only
python3 -m pytest tests/test_aws.py

# Test Terraform modules
cd terraform && terraform validate

# Test carbon API integration
python3 -m pytest tests/test_carbon_api.py
```

## 🔧 Troubleshooting

### Common Issues

#### AWS Credentials Error

```bash
# Verify AWS credentials
aws sts get-caller-identity

# Re-configure if needed
aws configure
```

#### Terraform State Issues

```bash
# Refresh Terraform state
cd terraform
terraform refresh

# Force unlock if locked
terraform force-unlock <lock-id>
```

#### API Token Issues

```bash
# Test Electricity Maps API
curl -H "auth-token: YOUR_TOKEN" \
  "https://api.electricitymap.org/v3/carbon-intensity/latest?zone=US-CAL-CISO"
```

#### Health Check Failures

```bash
# Check instance status
aws ec2 describe-instance-status --instance-ids <instance-id>

# SSH into instance for debugging
ssh -i your-key.pem ec2-user@<public-ip>
```

### Log Analysis

Check logs for detailed error information:

```bash
# Check deployment logs
grep ERROR logs/deployment_*.json

# Check application logs on EC2
ssh ec2-user@<instance-ip> "sudo journalctl -u carbon-aware"
```

## 🤝 Contributing

We welcome contributions! Here's how to get involved:

### Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/CarbonAware-Redeployment.git
cd CarbonAware-Redeployment

# Create feature branch
git checkout -b feature/your-feature-name

# Install in development mode
pip install -e .
```

### Contribution Areas

- 🌟 **New Features**: Multi-cloud support, advanced scheduling
- 📚 **Documentation**: Tutorials, examples, translations
- 🐛 **Bug Fixes**: Issue resolution and improvements
- 🧪 **Testing**: Additional test cases and coverage
- 🎨 **UI/UX**: Dashboard and visualization improvements

### Submission Process

1. Fork the repository
2. Create your feature branch
3. Commit changes with descriptive messages
4. Push to your fork
5. Open a Pull Request

## 📈 Roadmap

### Current Release (v1.2.0)

- ✅ Automated setup scripts
- ✅ Environment-specific configurations
- ✅ Docker support
- ✅ Enhanced monitoring
- ✅ Release packaging system

### Upcoming Features (v2.0.0)

- 🔄 Multi-cloud support (Azure, GCP)
- 📊 Web dashboard for monitoring
- 🤖 Machine learning for prediction
- 📱 Mobile app for management
- 🔌 Kubernetes integration
- 🌐 Multi-region load balancing

## 📄 License

This project is licensed under the [MIT License](LICENSE). You are free to use, modify, and distribute this project while providing proper attribution.

## 🙏 Acknowledgments

- [Electricity Maps](https://www.electricitymaps.com/) for carbon intensity data
- AWS for cloud infrastructure
- The open-source community for continuous support

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/JeremLeOuf/CarbonAware-Redeployment/issues)
- **Discussions**: [GitHub Discussions](https://github.com/JeremLeOuf/CarbonAware-Redeployment/discussions)
- **Email**: Contact via GitHub profile

---

🌱 **Deploy sustainably, automate confidently, and contribute proactively!**
