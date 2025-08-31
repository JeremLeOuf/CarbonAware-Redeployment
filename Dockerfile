# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Terraform
RUN wget https://releases.hashicorp.com/terraform/1.5.0/terraform_1.5.0_linux_amd64.zip \
    && unzip terraform_1.5.0_linux_amd64.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform_1.5.0_linux_amd64.zip

# Install AWS CLI
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

# Copy application files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make scripts executable
RUN chmod +x scripts/*.sh

ENTRYPOINT ["python3"]
CMD ["redeploy_auto.py"]