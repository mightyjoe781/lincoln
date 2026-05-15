# Lincoln — AWS Deployment Guide

This guide walks through deploying Lincoln to AWS using ECS Fargate, RDS PostgreSQL, ElastiCache Redis, and an Application Load Balancer. Every command is written to be run as-is after substituting the `<PLACEHOLDER>` values. The guide is structured as eight sequential phases; complete them in order on a fresh AWS account or a dedicated environment.

---

## Architecture Overview

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Route 53 (optional)  ──►  ACM Certificate                  │
└─────────────────────────────────────────────────────────────┘
    │ HTTPS :443
    ▼
┌─────────────────────────────────────────────────────────────┐
│              Application Load Balancer (ALB)                 │
│           (public subnets, SG: 80/443 from 0.0.0.0/0)      │
└─────────────────────────────────────────────────────────────┘
    │ HTTP :8000 (internal)
    ▼
┌──────────────────────────────┐
│   ECS Fargate — API Service  │  ◄── SSM Parameter Store
│   (private subnet, 512 CPU / │      (secrets injection)
│    1024 MB, desired: 2)      │
│   CMD: uvicorn app.main:app  │
└──────────────────────────────┘
    │                        │
    │ asyncpg :5432          │ redis :6379
    ▼                        ▼
┌─────────────────┐   ┌──────────────────────┐
│  RDS PostgreSQL │   │  ElastiCache Redis   │
│  (private sub.) │   │  (private subnet)    │
│  Multi-AZ prod  │   │  single-node dev     │
└─────────────────┘   └──────────────────────┘
    ▲                        ▲
    │ asyncpg :5432          │ redis :6379
    │                        │
┌──────────────────────────────┐
│   ECS Fargate — Worker Svc   │  ◄── SSM Parameter Store
│   (private subnet, 512 CPU / │
│    1024 MB, desired: 1)      │
│   CMD: celery -A             │
│     app.worker.celery_app    │
│     worker                   │
└──────────────────────────────┘
    │
    ▼ (optional)
┌─────────────────┐
│   S3 Bucket     │  ◄── IAM role attached to task
│   (uploads)     │
└─────────────────┘
```

### Component Rationale

| Component | Choice | Why not the alternative |
|---|---|---|
| **ECS Fargate** | Serverless containers | EKS is production-grade but adds 3–5× operational complexity for a single-app deployment. EC2 requires patching. |
| **RDS PostgreSQL 16** | Managed relational DB | Aurora is cost-effective at scale but 2–3× more expensive at low traffic. Self-managed PostgreSQL on EC2 requires manual backups, patching, and HA wiring. |
| **ElastiCache Redis** | Managed Redis | Self-managed Redis on EC2 has no automatic failover. ElastiCache handles replication, patching, and CloudWatch integration. |
| **ALB** | Layer-7 load balancer | NLB operates at Layer 4 — no path-based routing, no HTTP-to-HTTPS redirect, no host-based rules. |
| **SSM Parameter Store** | Secrets management | Secrets Manager costs $0.40/secret/month. SSM SecureString parameters are free and sufficient for a single-environment deployment. Use Secrets Manager if you need automatic rotation. |
| **ECR** | Container registry | Docker Hub has pull-rate limits that cause flaky CI. ECR is co-located with ECS, so pulls are free and fast. |

---

## Prerequisites

### Tools

```bash
# AWS CLI v2
aws --version   # must be 2.x

# Docker
docker --version

# jq (used in several commands below)
brew install jq   # macOS
apt-get install -y jq   # Debian/Ubuntu
```

Install AWS CLI v2 from https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html if not already installed.

### AWS Configuration

```bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region name: us-east-1          ← or your preferred region
# Default output format: json
```

Export the two variables you will use throughout this guide:

```bash
export AWS_REGION="us-east-1"
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account: $ACCOUNT_ID  Region: $AWS_REGION"
```

### Required IAM Permissions

The caller identity used to run these commands needs the following managed policies attached (or equivalent inline permissions). This is appropriate for a dedicated deployment IAM user; never use root credentials.

```
AmazonEC2FullAccess
AmazonECS_FullAccess
AmazonRDSFullAccess
AmazonElastiCacheFullAccess
AmazonEC2ContainerRegistryFullAccess
AmazonSSMFullAccess
AmazonS3FullAccess
IAMFullAccess
ElasticLoadBalancingFullAccess
CloudWatchFullAccess
```

For a least-privilege setup, scope each policy to the specific resources created in this guide using resource ARNs after the initial deployment.

---

## Phase 1 — Container Registry (ECR)

### 1.1 Create the ECR repository

```bash
aws ecr create-repository \
  --repository-name lincoln \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256 \
  --region $AWS_REGION

# Capture the repository URI for later steps
export ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/lincoln"
echo "ECR URI: $ECR_URI"
```

Enable tag immutability to prevent accidental overwrites of production images:

```bash
aws ecr put-image-tag-mutability \
  --repository-name lincoln \
  --image-tag-mutability IMMUTABLE \
  --region $AWS_REGION
```

### 1.2 Authenticate Docker to ECR

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
```

This token is valid for 12 hours. Re-run before pushing if your session is older.

### 1.3 Build and push the Lincoln image

```bash
cd /path/to/lincoln   # your local clone

# Tag with git SHA for traceability; also tag as latest
export IMAGE_TAG=$(git rev-parse --short HEAD)

docker build \
  --platform linux/amd64 \   # required when building on Apple Silicon (M1/M2/M3)
  -t lincoln:${IMAGE_TAG} \
  -t lincoln:latest \
  .

docker tag lincoln:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}
docker tag lincoln:latest       ${ECR_URI}:latest

docker push ${ECR_URI}:${IMAGE_TAG}
docker push ${ECR_URI}:latest
```

> **Note for Apple Silicon:** Always pass `--platform linux/amd64` when building for ECS Fargate. Fargate does not support ARM64 unless you explicitly configure the task definition's `runtimePlatform` for ARM64, which requires Graviton instances.

### 1.4 Verify the image exists

```bash
aws ecr list-images \
  --repository-name lincoln \
  --region $AWS_REGION \
  --query 'imageIds[*].imageTag' \
  --output table
```

---

## Phase 2 — Networking (VPC)

All Lincoln resources (RDS, Redis, ECS tasks) live in private subnets. Only the ALB sits in public subnets. This section creates the full network topology.

### 2.1 Create VPC and subnets

```bash
# VPC
VPC_ID=$(aws ec2 create-vpc \
  --cidr-block 10.0.0.0/16 \
  --query 'Vpc.VpcId' --output text)
aws ec2 create-tags --resources $VPC_ID \
  --tags Key=Name,Value=lincoln-vpc
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-support

echo "VPC: $VPC_ID"

# Public subnets (ALB) — one per AZ
PUB_SUBNET_1=$(aws ec2 create-subnet \
  --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 \
  --availability-zone ${AWS_REGION}a \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $PUB_SUBNET_1 \
  --tags Key=Name,Value=lincoln-public-1a

PUB_SUBNET_2=$(aws ec2 create-subnet \
  --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 \
  --availability-zone ${AWS_REGION}b \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $PUB_SUBNET_2 \
  --tags Key=Name,Value=lincoln-public-1b

# Private subnets (ECS, RDS, Redis) — one per AZ
PRIV_SUBNET_1=$(aws ec2 create-subnet \
  --vpc-id $VPC_ID --cidr-block 10.0.10.0/24 \
  --availability-zone ${AWS_REGION}a \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $PRIV_SUBNET_1 \
  --tags Key=Name,Value=lincoln-private-1a

PRIV_SUBNET_2=$(aws ec2 create-subnet \
  --vpc-id $VPC_ID --cidr-block 10.0.11.0/24 \
  --availability-zone ${AWS_REGION}b \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $PRIV_SUBNET_2 \
  --tags Key=Name,Value=lincoln-private-1b

echo "Public:  $PUB_SUBNET_1  $PUB_SUBNET_2"
echo "Private: $PRIV_SUBNET_1 $PRIV_SUBNET_2"
```

### 2.2 Internet Gateway and routing for public subnets

```bash
IGW_ID=$(aws ec2 create-internet-gateway \
  --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
aws ec2 create-tags --resources $IGW_ID --tags Key=Name,Value=lincoln-igw

PUB_RT=$(aws ec2 create-route-table \
  --vpc-id $VPC_ID --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PUB_RT \
  --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --subnet-id $PUB_SUBNET_1 --route-table-id $PUB_RT
aws ec2 associate-route-table --subnet-id $PUB_SUBNET_2 --route-table-id $PUB_RT
aws ec2 modify-subnet-attribute --subnet-id $PUB_SUBNET_1 \
  --map-public-ip-on-launch
aws ec2 modify-subnet-attribute --subnet-id $PUB_SUBNET_2 \
  --map-public-ip-on-launch
```

### 2.3 NAT Gateway for private subnet egress

ECS tasks in private subnets need outbound internet access to pull ECR images and call SSM. A NAT Gateway in each public subnet provides this.

```bash
# Allocate EIPs
EIP_1=$(aws ec2 allocate-address --domain vpc \
  --query 'AllocationId' --output text)
EIP_2=$(aws ec2 allocate-address --domain vpc \
  --query 'AllocationId' --output text)

# Create NAT Gateways (one per AZ for HA; use one for dev to save ~$33/month)
NAT_1=$(aws ec2 create-nat-gateway \
  --subnet-id $PUB_SUBNET_1 --allocation-id $EIP_1 \
  --query 'NatGateway.NatGatewayId' --output text)
NAT_2=$(aws ec2 create-nat-gateway \
  --subnet-id $PUB_SUBNET_2 --allocation-id $EIP_2 \
  --query 'NatGateway.NatGatewayId' --output text)

echo "Waiting for NAT gateways to become available (~60 s)..."
aws ec2 wait nat-gateway-available --nat-gateway-ids $NAT_1 $NAT_2

# Private route tables
PRIV_RT_1=$(aws ec2 create-route-table \
  --vpc-id $VPC_ID --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PRIV_RT_1 \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_1
aws ec2 associate-route-table \
  --subnet-id $PRIV_SUBNET_1 --route-table-id $PRIV_RT_1

PRIV_RT_2=$(aws ec2 create-route-table \
  --vpc-id $VPC_ID --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PRIV_RT_2 \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_2
aws ec2 associate-route-table \
  --subnet-id $PRIV_SUBNET_2 --route-table-id $PRIV_RT_2
```

> **Dev cost tip:** To avoid NAT Gateway charges in non-production environments, use a single NAT Gateway and accept that an AZ failure will take down outbound egress. Delete the second EIP and NAT Gateway, and point both private route tables at `$NAT_1`.

### 2.4 Security Groups

Create each security group and add rules referencing other groups by ID. Rules are listed as `port/protocol source`.

```bash
# --- ALB: accepts public HTTP and HTTPS ---
SG_ALB=$(aws ec2 create-security-group \
  --group-name lincoln-alb \
  --description "Lincoln ALB" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_ALB \
  --ip-permissions \
    IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}] \
    IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]

# --- App: accepts 8000 from ALB only ---
SG_APP=$(aws ec2 create-security-group \
  --group-name lincoln-app \
  --description "Lincoln API (ECS)" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_APP \
  --protocol tcp --port 8000 --source-group $SG_ALB

# --- Worker: no inbound rules (outbound only) ---
SG_WORKER=$(aws ec2 create-security-group \
  --group-name lincoln-worker \
  --description "Lincoln Celery Worker (ECS)" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)
# No ingress rules needed — workers initiate all connections outbound

# --- RDS: accepts 5432 from App and Worker ---
SG_RDS=$(aws ec2 create-security-group \
  --group-name lincoln-rds \
  --description "Lincoln RDS PostgreSQL" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_RDS \
  --protocol tcp --port 5432 --source-group $SG_APP
aws ec2 authorize-security-group-ingress --group-id $SG_RDS \
  --protocol tcp --port 5432 --source-group $SG_WORKER

# --- Redis: accepts 6379 from App and Worker ---
SG_REDIS=$(aws ec2 create-security-group \
  --group-name lincoln-redis \
  --description "Lincoln ElastiCache Redis" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_REDIS \
  --protocol tcp --port 6379 --source-group $SG_APP
aws ec2 authorize-security-group-ingress --group-id $SG_REDIS \
  --protocol tcp --port 6379 --source-group $SG_WORKER

echo "SGs: ALB=$SG_ALB  APP=$SG_APP  WORKER=$SG_WORKER  RDS=$SG_RDS  REDIS=$SG_REDIS"
```

---

## Phase 3 — Data Layer

### 3.1 RDS PostgreSQL 16

#### Subnet group

```bash
aws rds create-db-subnet-group \
  --db-subnet-group-name lincoln-db-subnets \
  --db-subnet-group-description "Lincoln RDS subnets" \
  --subnet-ids $PRIV_SUBNET_1 $PRIV_SUBNET_2
```

#### Parameter group

```bash
aws rds create-db-parameter-group \
  --db-parameter-group-name lincoln-pg16 \
  --db-parameter-group-family postgres16 \
  --description "Lincoln PostgreSQL 16 parameters"

# Enable pg_stat_statements for query performance monitoring
aws rds modify-db-parameter-group \
  --db-parameter-group-name lincoln-pg16 \
  --parameters \
    ParameterName=shared_preload_libraries,ParameterValue=pg_stat_statements,ApplyMethod=pending-reboot \
    ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate \
    ParameterName=log_connections,ParameterValue=1,ApplyMethod=immediate \
    ParameterName=log_disconnections,ParameterValue=1,ApplyMethod=immediate
```

#### Dev instance (free-tier eligible)

```bash
aws rds create-db-instance \
  --db-instance-identifier lincoln-dev \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --engine-version 16 \
  --master-username lincoln \
  --master-user-password "<STRONG_DB_PASSWORD>" \
  --db-name lincoln \
  --allocated-storage 20 \
  --storage-type gp2 \
  --no-multi-az \
  --no-publicly-accessible \
  --vpc-security-group-ids $SG_RDS \
  --db-subnet-group-name lincoln-db-subnets \
  --db-parameter-group-name lincoln-pg16 \
  --backup-retention-period 7 \
  --deletion-protection \
  --tags Key=Environment,Value=dev Key=Project,Value=lincoln
```

#### Production instance

```bash
aws rds create-db-instance \
  --db-instance-identifier lincoln-prod \
  --db-instance-class db.t3.small \
  --engine postgres \
  --engine-version 16 \
  --master-username lincoln \
  --master-user-password "<STRONG_DB_PASSWORD>" \
  --db-name lincoln \
  --allocated-storage 50 \
  --storage-type gp3 \
  --iops 3000 \
  --multi-az \
  --no-publicly-accessible \
  --vpc-security-group-ids $SG_RDS \
  --db-subnet-group-name lincoln-db-subnets \
  --db-parameter-group-name lincoln-pg16 \
  --backup-retention-period 14 \
  --preferred-backup-window "02:00-03:00" \
  --preferred-maintenance-window "sun:04:00-sun:05:00" \
  --deletion-protection \
  --enable-performance-insights \
  --tags Key=Environment,Value=production Key=Project,Value=lincoln
```

#### Wait and retrieve the endpoint

```bash
echo "Waiting for RDS instance (can take 5–10 minutes)..."
aws rds wait db-instance-available --db-instance-identifier lincoln-prod

RDS_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier lincoln-prod \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)
echo "RDS endpoint: $RDS_ENDPOINT"
```

#### Connection string format for Lincoln

Lincoln uses asyncpg. The `fix_asyncpg_scheme` validator in `app/core/config.py` rewrites `postgresql://` to `postgresql+asyncpg://` automatically, so either scheme works. The canonical form is:

```
postgresql+asyncpg://lincoln:<PASSWORD>@<RDS_ENDPOINT>:5432/lincoln
```

### 3.2 ElastiCache Redis

#### Subnet group

```bash
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name lincoln-redis-subnets \
  --cache-subnet-group-description "Lincoln ElastiCache subnets" \
  --subnet-ids $PRIV_SUBNET_1 $PRIV_SUBNET_2
```

#### Dev cluster (single node)

```bash
aws elasticache create-cache-cluster \
  --cache-cluster-id lincoln-dev \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --engine-version 7.1 \
  --num-cache-nodes 1 \
  --cache-subnet-group-name lincoln-redis-subnets \
  --security-group-ids $SG_REDIS \
  --tags Key=Environment,Value=dev Key=Project,Value=lincoln
```

#### Production cluster (single node with automatic failover via replication group)

For production, use a replication group so ElastiCache can promote a replica if the primary fails:

```bash
aws elasticache create-replication-group \
  --replication-group-id lincoln-prod \
  --replication-group-description "Lincoln production Redis" \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --engine-version 7.1 \
  --num-cache-clusters 2 \
  --automatic-failover-enabled \
  --cache-subnet-group-name lincoln-redis-subnets \
  --security-group-ids $SG_REDIS \
  --at-rest-encryption-enabled \
  --transit-encryption-enabled \
  --tags Key=Environment,Value=production Key=Project,Value=lincoln
```

#### Retrieve endpoint

```bash
REDIS_ENDPOINT=$(aws elasticache describe-cache-clusters \
  --cache-cluster-id lincoln-dev \
  --show-cache-node-info \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \
  --output text)
echo "Redis endpoint: $REDIS_ENDPOINT"
```

#### Connection string format

```
redis://<REDIS_ENDPOINT>:6379/0
```

If transit encryption is enabled (production), use:

```
rediss://<REDIS_ENDPOINT>:6379/0
```

---

## Phase 4 — Secrets Management (SSM Parameter Store)

All sensitive values are stored as `SecureString` parameters encrypted with the default AWS-managed KMS key. ECS tasks retrieve them at launch via IAM role — secrets never appear in task definition JSON or environment files.

### 4.1 Store parameters

Use the naming convention `/lincoln/<environment>/<VAR_NAME>`.

```bash
ENV=production   # change to 'dev' for dev environment

# Database URL — asyncpg connection string
aws ssm put-parameter \
  --name "/lincoln/${ENV}/DATABASE_URL" \
  --value "postgresql+asyncpg://lincoln:<DB_PASSWORD>@${RDS_ENDPOINT}:5432/lincoln" \
  --type SecureString \
  --description "Lincoln PostgreSQL connection string" \
  --overwrite

# Redis URL
aws ssm put-parameter \
  --name "/lincoln/${ENV}/REDIS_URL" \
  --value "redis://${REDIS_ENDPOINT}:6379/0" \
  --type SecureString \
  --description "Lincoln Redis connection string" \
  --overwrite

# JWT secret — generate a strong random value
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
aws ssm put-parameter \
  --name "/lincoln/${ENV}/JWT_SECRET_KEY" \
  --value "$JWT_SECRET" \
  --type SecureString \
  --description "Lincoln JWT signing secret" \
  --overwrite

# Admin credentials
aws ssm put-parameter \
  --name "/lincoln/${ENV}/ADMIN_EMAIL" \
  --value "admin@yourdomain.com" \
  --type SecureString \
  --description "Lincoln default admin email" \
  --overwrite

aws ssm put-parameter \
  --name "/lincoln/${ENV}/ADMIN_PASSWORD" \
  --value "<STRONG_ADMIN_PASSWORD>" \
  --type SecureString \
  --description "Lincoln default admin password" \
  --overwrite

# Registration token (leave blank to allow open registration)
REGISTRATION_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
aws ssm put-parameter \
  --name "/lincoln/${ENV}/REGISTRATION_TOKEN" \
  --value "$REGISTRATION_TOKEN" \
  --type SecureString \
  --description "Lincoln registration gate token" \
  --overwrite

echo "Registration token (save this): $REGISTRATION_TOKEN"
```

### 4.2 IAM task execution role

ECS needs a role to pull the parameters on behalf of the task container. Create a task execution role with SSM read permissions:

```bash
# Trust policy document
cat > /tmp/ecs-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create the execution role
aws iam create-role \
  --role-name lincoln-ecs-execution-role \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json

# Attach the managed ECS execution policy (allows ECR pull + CloudWatch logs)
aws iam attach-role-policy \
  --role-name lincoln-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Add SSM GetParameter permission for /lincoln/* parameters
cat > /tmp/ssm-read-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/*"
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:${AWS_REGION}:${ACCOUNT_ID}:key/aws/ssm"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name lincoln-ecs-execution-role \
  --policy-name lincoln-ssm-read \
  --policy-document file:///tmp/ssm-read-policy.json

EXEC_ROLE_ARN=$(aws iam get-role \
  --role-name lincoln-ecs-execution-role \
  --query 'Role.Arn' --output text)
echo "Execution role ARN: $EXEC_ROLE_ARN"
```

### 4.3 IAM task role (application permissions)

The task role is assumed by the running application process (not ECS infrastructure). It will later be expanded with S3 permissions in Phase 7.

```bash
aws iam create-role \
  --role-name lincoln-ecs-task-role \
  --assume-role-policy-document file:///tmp/ecs-trust-policy.json

TASK_ROLE_ARN=$(aws iam get-role \
  --role-name lincoln-ecs-task-role \
  --query 'Role.Arn' --output text)
echo "Task role ARN: $TASK_ROLE_ARN"
```

---

## Phase 5 — ECS Setup

### 5.1 Create the ECS cluster

```bash
aws ecs create-cluster \
  --cluster-name lincoln \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy \
    capacityProvider=FARGATE,weight=1,base=1 \
  --settings name=containerInsights,value=enabled \
  --tags key=Project,value=lincoln
```

Container Insights adds per-task CPU/memory metrics to CloudWatch at a small additional cost (~$0.50/GB of logs). Disable it with `value=disabled` for dev.

### 5.2 CloudWatch log groups

```bash
aws logs create-log-group \
  --log-group-name /ecs/lincoln-api \
  --retention-in-days 30

aws logs create-log-group \
  --log-group-name /ecs/lincoln-worker \
  --retention-in-days 30
```

### 5.3 Task definition — API service

The `secrets` array tells ECS to pull each SSM parameter at launch and inject it as an environment variable. The container never sees the raw SSM call.

```bash
ENV=production

cat > /tmp/lincoln-api-task.json << EOF
{
  "family": "lincoln-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "runtimePlatform": {
    "operatingSystemFamily": "LINUX",
    "cpuArchitecture": "X86_64"
  },
  "containerDefinitions": [
    {
      "name": "api",
      "image": "${ECR_URI}:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        { "name": "ENVIRONMENT",                 "value": "${ENV}" },
        { "name": "JWT_ALGORITHM",               "value": "HS256" },
        { "name": "ACCESS_TOKEN_EXPIRE_MINUTES", "value": "30" },
        { "name": "MAX_UPLOAD_SIZE_BYTES",       "value": "20971520" },
        { "name": "UPLOAD_DIR",                  "value": "/tmp/lincoln_uploads" }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/DATABASE_URL"
        },
        {
          "name": "REDIS_URL",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/REDIS_URL"
        },
        {
          "name": "JWT_SECRET_KEY",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/JWT_SECRET_KEY"
        },
        {
          "name": "ADMIN_EMAIL",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/ADMIN_EMAIL"
        },
        {
          "name": "ADMIN_PASSWORD",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/ADMIN_PASSWORD"
        },
        {
          "name": "REGISTRATION_TOKEN",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/REGISTRATION_TOKEN"
        }
      ],
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "curl -f http://localhost:8000/health || exit 1"
        ],
        "interval": 30,
        "timeout": 10,
        "retries": 3,
        "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/lincoln-api",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "api"
        }
      },
      "stopTimeout": 30
    }
  ]
}
EOF

aws ecs register-task-definition \
  --cli-input-json file:///tmp/lincoln-api-task.json \
  --region $AWS_REGION
```

> **startPeriod note:** The container CMD runs `alembic upgrade head` and `python -m app.scripts.seed` before starting uvicorn. On first boot against an empty database this can take 30–60 seconds. The `startPeriod: 60` tells ECS not to count health check failures during that window.

### 5.4 Task definition — Celery worker

The worker uses the same image but overrides the CMD. It has no port mappings and no ALB health check — ECS monitors it by task state only.

```bash
cat > /tmp/lincoln-worker-task.json << EOF
{
  "family": "lincoln-worker",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "runtimePlatform": {
    "operatingSystemFamily": "LINUX",
    "cpuArchitecture": "X86_64"
  },
  "containerDefinitions": [
    {
      "name": "worker",
      "image": "${ECR_URI}:latest",
      "essential": true,
      "command": [
        "celery",
        "-A", "app.worker.celery_app",
        "worker",
        "--loglevel=info",
        "--concurrency=2"
      ],
      "environment": [
        { "name": "ENVIRONMENT",           "value": "${ENV}" },
        { "name": "MAX_UPLOAD_SIZE_BYTES", "value": "20971520" },
        { "name": "UPLOAD_DIR",            "value": "/tmp/lincoln_uploads" }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/DATABASE_URL"
        },
        {
          "name": "REDIS_URL",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/REDIS_URL"
        },
        {
          "name": "JWT_SECRET_KEY",
          "valueFrom": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/lincoln/${ENV}/JWT_SECRET_KEY"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/lincoln-worker",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "worker"
        }
      },
      "stopTimeout": 120
    }
  ]
}
EOF

aws ecs register-task-definition \
  --cli-input-json file:///tmp/lincoln-worker-task.json \
  --region $AWS_REGION
```

> **stopTimeout for workers:** Celery workers receive SIGTERM on ECS task stop. Setting `stopTimeout: 120` gives in-flight parse jobs up to 2 minutes to complete before ECS sends SIGKILL. Pair this with `--max-tasks-per-child=50` in production to prevent memory accumulation.

### 5.5 ECS services

Create the target group first (Phase 6 covers the ALB itself), then create the services. The API service references the target group; the worker service does not.

**API service:**

```bash
# TARGET_GROUP_ARN is created in Phase 6 — run Phase 6.1–6.2 first, then return here
aws ecs create-service \
  --cluster lincoln \
  --service-name lincoln-api \
  --task-definition lincoln-api \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[$PRIV_SUBNET_1,$PRIV_SUBNET_2],
    securityGroups=[$SG_APP],
    assignPublicIp=DISABLED
  }" \
  --load-balancers "targetGroupArn=${TARGET_GROUP_ARN},containerName=api,containerPort=8000" \
  --health-check-grace-period-seconds 90 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},
    minimumHealthyPercent=100,maximumPercent=200" \
  --enable-execute-command \
  --tags key=Project,value=lincoln
```

**Worker service:**

```bash
aws ecs create-service \
  --cluster lincoln \
  --service-name lincoln-worker \
  --task-definition lincoln-worker \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[$PRIV_SUBNET_1,$PRIV_SUBNET_2],
    securityGroups=[$SG_WORKER],
    assignPublicIp=DISABLED
  }" \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},
    minimumHealthyPercent=100,maximumPercent=200" \
  --enable-execute-command \
  --tags key=Project,value=lincoln
```

### 5.6 Auto-scaling

```bash
# Register API service as a scalable target
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/lincoln/lincoln-api \
  --min-capacity 2 \
  --max-capacity 10

# Scale out when average CPU exceeds 70% for 2 minutes
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/lincoln/lincoln-api \
  --policy-name lincoln-api-cpu \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 70.0,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
    },
    "ScaleInCooldown": 300,
    "ScaleOutCooldown": 60
  }'
```

---

## Phase 6 — Load Balancer (ALB)

### 6.1 Create the ALB

```bash
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name lincoln-alb \
  --subnets $PUB_SUBNET_1 $PUB_SUBNET_2 \
  --security-groups $SG_ALB \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4 \
  --tags Key=Project,Value=lincoln \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)

ALB_DNS=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)

echo "ALB ARN: $ALB_ARN"
echo "ALB DNS: $ALB_DNS"
```

### 6.2 Target group

```bash
TARGET_GROUP_ARN=$(aws elbv2 create-target-group \
  --name lincoln-api \
  --protocol HTTP \
  --port 8000 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-protocol HTTP \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 10 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --matcher HttpCode=200 \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)

echo "Target group ARN: $TARGET_GROUP_ARN"
# Use this value in Phase 5.5 when creating the API ECS service
```

### 6.3 HTTPS listener with ACM certificate

> **Certificate provisioning is out of scope for this guide.** Request a certificate through AWS Certificate Manager (ACM) at https://console.aws.amazon.com/acm/ or via:
> ```bash
> aws acm request-certificate \
>   --domain-name yourdomain.com \
>   --subject-alternative-names "*.yourdomain.com" \
>   --validation-method DNS
> ```
> Complete DNS validation, then retrieve the certificate ARN:
> ```bash
> CERT_ARN=$(aws acm list-certificates \
>   --query "CertificateSummaryList[?DomainName=='yourdomain.com'].CertificateArn" \
>   --output text)
> ```

```bash
# HTTPS listener (port 443) forwarding to the target group
HTTPS_LISTENER_ARN=$(aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTPS \
  --port 443 \
  --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
  --certificates CertificateArn=${CERT_ARN} \
  --default-actions Type=forward,TargetGroupArn=${TARGET_GROUP_ARN} \
  --query 'Listeners[0].ListenerArn' --output text)

# HTTP listener (port 80) redirecting to HTTPS
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions \
    Type=redirect,RedirectConfig="{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}"
```

> **SSL policy:** `ELBSecurityPolicy-TLS13-1-2-2021-06` enforces TLS 1.2+ and prefers TLS 1.3. It drops support for older ciphers that have known weaknesses. Use `ELBSecurityPolicy-2016-08` only if you need to support very old clients.

### 6.4 Verify the deployment

```bash
# Wait for the service to stabilize
aws ecs wait services-stable \
  --cluster lincoln \
  --services lincoln-api

# Hit the health endpoint through the ALB
curl -f http://${ALB_DNS}/health
# Expected: {"status": "ok"}
```

---

## Phase 7 — S3 for File Storage (Optional but Recommended)

By default Lincoln uses `LocalFileStorage`, which writes uploaded files to `UPLOAD_DIR` on the container's ephemeral filesystem. This works for single-replica deployments but has two problems at scale:

1. Files are lost when a task is replaced or scaled in.
2. Two API replicas cannot share the same filesystem.

The `AbstractStorage` protocol in `app/storage/base.py` defines `save`, `delete`, and `exists` — swapping in an S3 implementation requires adding one file and changing one dependency injection call. This phase sets up the AWS infrastructure; the code change is described at the end of this section.

### 7.1 Create the S3 bucket

```bash
BUCKET_NAME="lincoln-uploads-${ACCOUNT_ID}-${AWS_REGION}"

aws s3api create-bucket \
  --bucket $BUCKET_NAME \
  --region $AWS_REGION \
  $([ "$AWS_REGION" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=$AWS_REGION")

# Block all public access
aws s3api put-public-access-block \
  --bucket $BUCKET_NAME \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,\
BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable versioning (allows recovery of overwritten uploads)
aws s3api put-bucket-versioning \
  --bucket $BUCKET_NAME \
  --versioning-configuration Status=Enabled

# Enable server-side encryption at rest
aws s3api put-bucket-encryption \
  --bucket $BUCKET_NAME \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

# Lifecycle rule — delete old versions after 90 days
aws s3api put-bucket-lifecycle-configuration \
  --bucket $BUCKET_NAME \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "delete-old-versions",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
    }]
  }'

echo "Bucket: $BUCKET_NAME"
```

### 7.2 IAM policy for ECS task role

```bash
cat > /tmp/s3-task-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:HeadObject"
      ],
      "Resource": "arn:aws:s3:::${BUCKET_NAME}/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::${BUCKET_NAME}"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name lincoln-ecs-task-role \
  --policy-name lincoln-s3-uploads \
  --policy-document file:///tmp/s3-task-policy.json
```

### 7.3 Store the bucket name in SSM

```bash
aws ssm put-parameter \
  --name "/lincoln/${ENV}/S3_BUCKET" \
  --value "$BUCKET_NAME" \
  --type String \
  --description "Lincoln S3 uploads bucket" \
  --overwrite
```

### 7.4 Code changes required

Create `app/storage/s3.py`:

```python
import boto3
from pathlib import Path


class S3FileStorage:
    def __init__(self, bucket: str, prefix: str = "uploads"):
        self.bucket = bucket
        self.prefix = prefix
        self._client = boto3.client("s3")   # uses task role credentials automatically

    def _key(self, original_filename: str, checksum: str) -> str:
        ext = Path(original_filename).suffix
        return f"{self.prefix}/{checksum}{ext}"

    async def save(self, data: bytes, original_filename: str, checksum: str) -> str:
        key = self._key(original_filename, checksum)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    async def delete(self, file_path: str) -> None:
        # file_path is the s3:// URI returned by save()
        key = file_path.split("/", 3)[-1]
        self._client.delete_object(Bucket=self.bucket, Key=key)

    async def exists(self, file_path: str) -> bool:
        import botocore.exceptions
        key = file_path.split("/", 3)[-1]
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False
```

In `app/core/config.py`, add:

```python
s3_bucket: str = ""   # if set, S3FileStorage is used instead of LocalFileStorage
```

In `app/main.py` (or wherever the storage dependency is injected), update the factory:

```python
from app.core.config import settings
from app.storage.local import LocalFileStorage
from app.storage.s3 import S3FileStorage

def get_storage():
    if settings.s3_bucket:
        return S3FileStorage(bucket=settings.s3_bucket)
    return LocalFileStorage(base_dir=settings.upload_dir)
```

Add `boto3` to `pyproject.toml` dependencies, then add `S3_BUCKET` to the task definition environment/secrets and the SSM parameter.

---

## Phase 8 — CI/CD Integration

The existing `.github/workflows/ci.yml` runs lint and tests. Add a second workflow file for deployment that triggers on merge to `main`.

### 8.1 GitHub repository secrets

In your GitHub repository go to **Settings → Secrets and variables → Actions** and add:

| Secret name | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key with ECR push + ECS deploy permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret key |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_ACCOUNT_ID` | Your 12-digit account ID |

Create a dedicated IAM user for CI with only the permissions it needs:

```bash
aws iam create-user --user-name lincoln-ci

cat > /tmp/ci-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:DescribeImages"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "iam:PassRole"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-user-policy \
  --user-name lincoln-ci \
  --policy-name lincoln-ci-deploy \
  --policy-document file:///tmp/ci-policy.json

aws iam create-access-key --user-name lincoln-ci
# Save the AccessKeyId and SecretAccessKey output — this is shown only once
```

### 8.2 Deployment workflow

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to AWS ECS

on:
  push:
    branches: [main, master]

env:
  AWS_REGION:    ${{ secrets.AWS_REGION }}
  ECR_REGISTRY:  ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.${{ secrets.AWS_REGION }}.amazonaws.com
  ECR_REPOSITORY: lincoln
  ECS_CLUSTER:   lincoln
  API_SERVICE:   lincoln-api
  WORKER_SERVICE: lincoln-worker

jobs:
  deploy:
    name: Build, Push, Deploy
    runs-on: ubuntu-latest
    permissions:
      contents: read

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region:            ${{ secrets.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push Docker image
        id: build
        env:
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build \
            --platform linux/amd64 \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:latest \
            .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> $GITHUB_OUTPUT

      - name: Download current API task definition
        run: |
          aws ecs describe-task-definition \
            --task-definition lincoln-api \
            --query taskDefinition \
            > /tmp/lincoln-api-task-def.json

      - name: Update API task definition with new image
        id: api-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: /tmp/lincoln-api-task-def.json
          container-name:  api
          image:           ${{ steps.build.outputs.image }}

      - name: Deploy API service
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition:        ${{ steps.api-task-def.outputs.task-definition }}
          service:                ${{ env.API_SERVICE }}
          cluster:                ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
          # Rolling deployment: keep 100% capacity during rollout
          # New tasks are launched before old ones are stopped (200% max)

      - name: Download current Worker task definition
        run: |
          aws ecs describe-task-definition \
            --task-definition lincoln-worker \
            --query taskDefinition \
            > /tmp/lincoln-worker-task-def.json

      - name: Update Worker task definition with new image
        id: worker-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: /tmp/lincoln-worker-task-def.json
          container-name:  worker
          image:           ${{ steps.build.outputs.image }}

      - name: Deploy Worker service
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition:        ${{ steps.worker-task-def.outputs.task-definition }}
          service:                ${{ env.WORKER_SERVICE }}
          cluster:                ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
```

### 8.3 Rolling deployment behaviour

The ECS services were created with:

- `minimumHealthyPercent: 100` — ECS will never reduce below the desired count. During a deploy, new tasks are started before old ones are stopped.
- `maximumPercent: 200` — ECS can temporarily run twice the desired count (e.g., 4 tasks when desired is 2) during rollout.
- `deploymentCircuitBreaker: enable=true, rollback=true` — if new tasks fail health checks, ECS automatically rolls back to the previous task definition revision.

This means a two-replica deployment (`desired_count: 2`) will briefly run four tasks during the rollout, then drain and stop the two old ones only after the two new ones are healthy. Zero-downtime is guaranteed as long as your ALB health check (`/health`) passes on the new version.

---

## Cost Estimate

All prices are for `us-east-1`. Costs fluctuate; verify at https://aws.amazon.com/pricing/.

### Dev tier (single developer, low traffic)

| Service | Spec | Monthly cost |
|---|---|---|
| ECS Fargate — API | 0.5 vCPU × 1 GB, 1 task, ~730 hrs | ~$14 |
| ECS Fargate — Worker | 0.5 vCPU × 1 GB, 1 task, ~730 hrs | ~$14 |
| RDS PostgreSQL | db.t3.micro, single-AZ, 20 GB gp2 | ~$15 (free tier: 750 hrs/mo first 12 months) |
| ElastiCache Redis | cache.t3.micro, single node | ~$12 |
| ALB | 1 ALB, ~1 LCU | ~$20 |
| NAT Gateway | 1 gateway, minimal data | ~$33 + data |
| ECR storage | ~1 GB | ~$0.10 |
| CloudWatch logs | 30-day retention, ~1 GB/mo | ~$0.50 |
| **Total** | | **~$109/mo** |

> Free-tier note: RDS db.t3.micro is free for 750 hours per month during the first 12 months of a new AWS account. This covers one instance running continuously.

### Production tier (multi-AZ, redundant)

| Service | Spec | Monthly cost |
|---|---|---|
| ECS Fargate — API | 1 vCPU × 2 GB, 2 tasks (desired), ~730 hrs | ~$112 |
| ECS Fargate — Worker | 0.5 vCPU × 1 GB, 1 task, ~730 hrs | ~$14 |
| RDS PostgreSQL | db.t3.small, Multi-AZ, 50 GB gp3 | ~$70 |
| ElastiCache Redis | cache.t3.micro replication group (2 nodes) | ~$24 |
| ALB | 1 ALB, ~5 LCU | ~$25 |
| NAT Gateway | 2 gateways (HA), moderate data | ~$70 + data |
| ECR storage | ~2 GB | ~$0.20 |
| CloudWatch (Insights + logs) | 30-day retention | ~$5 |
| S3 (optional uploads) | 10 GB storage + requests | ~$1 |
| **Total** | | **~$321/mo** |

**Cost reduction options:**
- Use `FARGATE_SPOT` for the worker service (up to 70% discount; tasks may be interrupted, but Celery handles restarts gracefully via acknowledgement after task completion).
- Use a single NAT Gateway for dev and staging environments.
- Set CloudWatch log retention to 7 days for non-production log groups.
- Delete unused ECR images older than 30 days using a lifecycle policy.

---

## Quick Reference

### All commands in order

```bash
# 0. Prerequisites
export AWS_REGION="us-east-1"
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 1. ECR
aws ecr create-repository --repository-name lincoln --region $AWS_REGION
export ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/lincoln"
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker build --platform linux/amd64 -t ${ECR_URI}:latest .
docker push ${ECR_URI}:latest

# 2. VPC (condensed — see Phase 2 for full commands)
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 --query 'Vpc.VpcId' --output text)
# ... create subnets, IGW, NAT, route tables, security groups

# 3. Data layer
aws rds create-db-subnet-group ...
aws rds create-db-instance --db-instance-identifier lincoln-prod ...
aws elasticache create-replication-group --replication-group-id lincoln-prod ...

# 4. SSM secrets
aws ssm put-parameter --name "/lincoln/production/DATABASE_URL" --type SecureString --value "..."
aws ssm put-parameter --name "/lincoln/production/REDIS_URL"    --type SecureString --value "..."
aws ssm put-parameter --name "/lincoln/production/JWT_SECRET_KEY" --type SecureString --value "..."
aws ssm put-parameter --name "/lincoln/production/ADMIN_EMAIL"  --type SecureString --value "..."
aws ssm put-parameter --name "/lincoln/production/ADMIN_PASSWORD" --type SecureString --value "..."
aws ssm put-parameter --name "/lincoln/production/REGISTRATION_TOKEN" --type SecureString --value "..."

# 5. IAM roles
aws iam create-role --role-name lincoln-ecs-execution-role ...
aws iam create-role --role-name lincoln-ecs-task-role ...

# 6. ECS cluster + task definitions
aws ecs create-cluster --cluster-name lincoln
aws ecs register-task-definition --cli-input-json file:///tmp/lincoln-api-task.json
aws ecs register-task-definition --cli-input-json file:///tmp/lincoln-worker-task.json

# 7. ALB + target group
ALB_ARN=$(aws elbv2 create-load-balancer --name lincoln-alb --subnets ... --query '...' --output text)
TARGET_GROUP_ARN=$(aws elbv2 create-target-group --name lincoln-api --port 8000 ... --output text)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTPS --port 443 ...
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions Type=redirect,...

# 8. ECS services
aws ecs create-service --cluster lincoln --service-name lincoln-api \
  --load-balancers targetGroupArn=${TARGET_GROUP_ARN},containerName=api,containerPort=8000 ...
aws ecs create-service --cluster lincoln --service-name lincoln-worker ...

# 9. Verify
aws ecs wait services-stable --cluster lincoln --services lincoln-api lincoln-worker
curl -f http://$(aws elbv2 describe-load-balancers \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)/health
```

### Update a running service (manual deploy)

```bash
# Push a new image
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build --platform linux/amd64 -t ${ECR_URI}:${IMAGE_TAG} .
docker push ${ECR_URI}:${IMAGE_TAG}

# Force ECS to pull the new image (if using :latest tag)
aws ecs update-service \
  --cluster lincoln \
  --service lincoln-api \
  --force-new-deployment

aws ecs update-service \
  --cluster lincoln \
  --service lincoln-worker \
  --force-new-deployment
```

### Exec into a running task for debugging

```bash
TASK_ID=$(aws ecs list-tasks \
  --cluster lincoln \
  --service-name lincoln-api \
  --query 'taskArns[0]' --output text | awk -F/ '{print $NF}')

aws ecs execute-command \
  --cluster lincoln \
  --task $TASK_ID \
  --container api \
  --interactive \
  --command "/bin/bash"
```

The `--enable-execute-command` flag was passed during `create-service` to enable this. Requires the AWS Session Manager plugin installed locally.

### Environment variable reference

| Variable | Source | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | SSM SecureString | Yes | `postgresql+asyncpg://user:pass@host:5432/lincoln` |
| `REDIS_URL` | SSM SecureString | Yes | `redis://host:6379/0` |
| `JWT_SECRET_KEY` | SSM SecureString | Yes | Random hex string (64 chars recommended) |
| `ADMIN_EMAIL` | SSM SecureString | No | Creates admin user on first boot |
| `ADMIN_PASSWORD` | SSM SecureString | No | Required if `ADMIN_EMAIL` is set |
| `REGISTRATION_TOKEN` | SSM SecureString | No | If set, `/auth/register` requires `X-Registration-Token` header |
| `ENVIRONMENT` | Task definition env | Yes | Set to `production` |
| `JWT_ALGORITHM` | Task definition env | No | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Task definition env | No | Default `30` |
| `MAX_UPLOAD_SIZE_BYTES` | Task definition env | No | Default `20971520` (20 MB) |
| `UPLOAD_DIR` | Task definition env | No | Default `/tmp/lincoln_uploads` (use S3 in production) |
| `S3_BUCKET` | SSM String | No | Required only after the S3 storage adapter is implemented |

---

## Operational Notes

### Running database migrations

Migrations run automatically on API container startup (`alembic upgrade head` is part of the CMD). For manual runs or to run migrations before deploying a new version:

```bash
# Run a one-off ECS task using the same task definition but override CMD
aws ecs run-task \
  --cluster lincoln \
  --task-definition lincoln-api \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[$PRIV_SUBNET_1],
    securityGroups=[$SG_APP],
    assignPublicIp=DISABLED
  }" \
  --overrides '{
    "containerOverrides": [{
      "name": "api",
      "command": ["alembic", "upgrade", "head"]
    }]
  }'
```

### Checking service health

```bash
# Service event log (last 10 events)
aws ecs describe-services \
  --cluster lincoln \
  --services lincoln-api \
  --query 'services[0].events[:10]'

# CloudWatch logs (last 20 lines)
aws logs tail /ecs/lincoln-api --follow --since 5m
```

### Rotating the JWT secret

1. Generate a new secret: `python3 -c "import secrets; print(secrets.token_hex(32))"`
2. Update the SSM parameter: `aws ssm put-parameter --name "/lincoln/production/JWT_SECRET_KEY" --value "<NEW>" --type SecureString --overwrite`
3. Force a new deployment: `aws ecs update-service --cluster lincoln --service lincoln-api --force-new-deployment`
4. All existing tokens signed with the old key will be immediately invalid. Users will need to log in again.

### Teardown (destroy all resources)

```bash
# Stop services first
aws ecs update-service --cluster lincoln --service lincoln-api --desired-count 0
aws ecs update-service --cluster lincoln --service lincoln-worker --desired-count 0
aws ecs delete-service --cluster lincoln --service lincoln-api
aws ecs delete-service --cluster lincoln --service lincoln-worker

# Delete ALB and target group
aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN
aws elbv2 delete-target-group --target-group-arn $TARGET_GROUP_ARN

# Delete RDS (skip final snapshot for dev)
aws rds delete-db-instance \
  --db-instance-identifier lincoln-prod \
  --skip-final-snapshot \
  --delete-automated-backups

# Delete ElastiCache
aws elasticache delete-replication-group --replication-group-id lincoln-prod

# Delete NAT gateways and release EIPs
aws ec2 delete-nat-gateway --nat-gateway-id $NAT_1
aws ec2 delete-nat-gateway --nat-gateway-id $NAT_2
# Wait ~60 seconds for NAT gateways to fully delete before releasing EIPs
aws ec2 release-address --allocation-id $EIP_1
aws ec2 release-address --allocation-id $EIP_2

# Delete VPC (subnets, route tables, IGW, SGs must be deleted first)
aws ec2 delete-security-group --group-id $SG_APP
aws ec2 delete-security-group --group-id $SG_WORKER
aws ec2 delete-security-group --group-id $SG_RDS
aws ec2 delete-security-group --group-id $SG_REDIS
aws ec2 delete-security-group --group-id $SG_ALB
aws ec2 detach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
aws ec2 delete-internet-gateway --internet-gateway-id $IGW_ID
aws ec2 delete-subnet --subnet-id $PUB_SUBNET_1
aws ec2 delete-subnet --subnet-id $PUB_SUBNET_2
aws ec2 delete-subnet --subnet-id $PRIV_SUBNET_1
aws ec2 delete-subnet --subnet-id $PRIV_SUBNET_2
aws ec2 delete-vpc --vpc-id $VPC_ID

# Delete ECR repository
aws ecr delete-repository --repository-name lincoln --force

# Delete ECS cluster
aws ecs delete-cluster --cluster lincoln

# Delete SSM parameters
aws ssm delete-parameters --names \
  /lincoln/production/DATABASE_URL \
  /lincoln/production/REDIS_URL \
  /lincoln/production/JWT_SECRET_KEY \
  /lincoln/production/ADMIN_EMAIL \
  /lincoln/production/ADMIN_PASSWORD \
  /lincoln/production/REGISTRATION_TOKEN
```
