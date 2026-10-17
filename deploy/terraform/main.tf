# main.tf — DC-North AIOps cloud infrastructure (implementation-plan Phase 4).
#
# Reading order: providers → network → load balancer → registry → compute → database
# → secrets → GitHub deploy role → CloudFront. Every resource that costs money while
# idle carries a "COST:" comment with a rough monthly USD estimate (ap-south-1, Oct 2026
# list prices, before free tier). Totals are in deploy/deployment-brief.md.
#
# Rebuild contract (Phase 7): `terraform destroy` removes everything here. Terraform
# state (S3), the RDS snapshots and the DB password are kept OUTSIDE this config so a
# later `terraform apply -var snapshot_identifier=...` brings the same incidents back.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Phase     = "4-7"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name = var.project
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
  # DATABASE_URL as SQLAlchemy expects it. `postgresql://` resolves to the default
  # driver installed with the backend (psycopg2 or psycopg); adjust if backend pins one.
  database_url = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${var.db_name}"
}

# ================================================================= network ====
# VPC with 2 public subnets (ALB, NAT) and 2 private subnets (ECS tasks, RDS).
# Two AZs are the minimum an ALB and an RDS subnet group accept.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]
  tags              = { Name = "${local.name}-private-${local.azs[count.index]}", Tier = "private" }
}

# COST: one Elastic IP attached to a NAT gateway is free; idle EIPs are not.
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }
}

# COST: NAT gateway ≈ USD 0.045/h ≈ 33/month + 0.045/GB processed. The single biggest
# fixed cost here. It exists so private ECS tasks can pull the image from ECR and reach
# the IdP / ticketing APIs. ONE gateway (not one per AZ) is a deliberate course-budget
# trade-off: an AZ outage would stop egress, which is acceptable for a demo.
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${local.name}-nat" }
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-rt-public" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${local.name}-rt-private" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ------------------------------------------------------- security groups ----
# Three groups, one hop each: internet → ALB → ECS task → RDS. Nothing else.

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "ALB: HTTP from anywhere (CloudFront terminates HTTPS in front of it)"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs" {
  name        = "${local.name}-ecs"
  description = "ECS tasks: only the ALB may reach the container port"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "App port from ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "RDS: PostgreSQL only from ECS tasks (API and the one-off migration task)"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}

# =========================================================== load balancer ====
# COST: ALB ≈ USD 0.0225/h ≈ 16/month + LCU usage (negligible at demo traffic).
# DECISION: the ALB listens on plain HTTP. HTTPS needs a certificate, and ACM only
# issues one for a domain we control. CloudFront (below) gives a free *.cloudfront.net
# HTTPS hostname without owning a domain, so the browser always talks TLS; ALB↔CloudFront
# is HTTP inside AWS. Revisit when a real domain exists (then: ACM cert + 443 listener).

resource "aws_lb" "main" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip" # Fargate tasks register by IP
  vpc_id      = aws_vpc.main.id

  # Phase 5 evidence: `/healthz` 200 on the ALB. Same path the workflow curls.
  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 15 # seconds; short so rollouts finish quickly
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ================================================================ registry ====
# COST: ECR storage ≈ USD 0.10/GB-month; a 200 MB image × a few tags ≈ cents.
resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE" # the workflow re-points :latest on every release

  # force_delete = true: `terraform destroy` must succeed even with images inside, or
  # the Phase 7 "destroy → rebuild" exercise stalls on a non-empty repository.
  # The consequence is intentional and documented: images do NOT survive teardown; the
  # deploy workflow re-publishes them (deployment-brief.md, "what survives teardown").
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  # Keep storage bounded: 10 most recent images are enough for rollback.
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ================================================================= compute ====
# COST: Fargate 0.25 vCPU + 0.5 GB ≈ USD 0.0127/h ≈ 9/month per running task.
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "disabled" # COST: Container Insights adds CloudWatch metrics charges; off for the course
  }
}

# COST: CloudWatch Logs ≈ USD 0.50/GB ingested; 7-day retention keeps storage trivial.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 7
}

# Execution role: what ECS itself needs to START the task (pull image, write logs, read secret).
resource "aws_iam_role" "task_execution" {
  name = "${local.name}-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "read-database-url"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.database_url.arn]
    }]
  })
}

# Task role: what the APPLICATION may call. Nothing in v1 — it talks to RDS, the IdP and
# ticketing over the network, not to AWS APIs. Exists so permissions can be added later
# without changing the execution role.
resource "aws_iam_role" "task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # GitHub-hosted runners build amd64 images
  }

  container_definitions = jsonencode([{
    name      = "api" # deploy.yml CONTAINER_NAME must match
    image     = var.image
    essential = true
    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]
    environment = concat(
      [{ name = "ENV", value = var.environment }],
      [for k, v in var.app_environment : { name = k, value = v }]
    )
    secrets = [{
      name      = "DATABASE_URL"
      valueFrom = aws_secretsmanager_secret.database_url.arn
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Rolling update: start the new task, wait for the ALB health check, stop the old one.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true # a task that never becomes healthy rolls the service back automatically
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false # private subnets; egress via NAT
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  # The deploy workflow registers new task-definition revisions and updates the service.
  # Ignoring that attribute keeps `terraform apply` drift-free after every release
  # (Phase 4 completion evidence) instead of rolling the service back to var.image.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]
}

# ================================================================ database ====
resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
}

# COST: db.t4g.micro ≈ USD 0.016/h ≈ 12/month (free tier covers it for the first year)
# + 20 GB gp3 ≈ 2.5/month + backup storage (free up to the instance size).
resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password # same value on restore; a snapshot carries its original password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false # COST: Multi-AZ doubles the instance price; not needed for a demo

  # Phase 7 — backup and restoration -------------------------------------------
  # Automated daily backups kept 7 days (point-in-time restore window).
  backup_retention_period = 7
  backup_window           = "19:00-20:00" # UTC ≈ 00:30 IST, outside demo hours
  maintenance_window      = "sun:20:30-sun:21:30"

  # Belt and braces: even if someone destroys WITHOUT running backup.sh first, RDS takes a
  # final snapshot. The identifier must be unique per destroy, hence the timestamp.
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name}-db-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  copy_tags_to_snapshot     = true

  # Restore switch: when set, RDS creates the instance FROM the snapshot — same data,
  # same INC-nnn rows with their original opened timestamps.
  snapshot_identifier = var.snapshot_identifier != "" ? var.snapshot_identifier : null

  deletion_protection = false # must be false or `terraform destroy` cannot complete the exercise
  apply_immediately   = true

  lifecycle {
    # final_snapshot_identifier: timestamp() changes every plan; without this the instance
    #   would show drift forever. The value is fixed at creation and reused at destroy.
    # snapshot_identifier: only meaningful at creation. Ignoring it means passing the var
    #   against a LIVE database is a no-op rather than a destroy-and-replace.
    ignore_changes = [final_snapshot_identifier, snapshot_identifier]
  }
}

# ================================================================= secrets ====
# COST: Secrets Manager ≈ USD 0.40/secret/month + 0.05 per 10k API calls.
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.name}/database-url"
  description             = "SQLAlchemy DATABASE_URL for the API and migration tasks"
  recovery_window_in_days = 0 # delete immediately on destroy so the name is free for the rebuild
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

# ===================================================== GitHub OIDC deploy role ====
# No long-lived AWS keys in GitHub. The workflow exchanges its OIDC token for this role.
# Trust is restricted to ONE repository and ONE branch (the `sub` claim).

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS now validates GitHub's certificate chain itself; the thumbprints are still required
  # by the API. These are GitHub's published values.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_role" "github_deploy" {
  name = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # push to <branch> and workflow_dispatch on <branch> both present this sub.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.app.arn
      },
      {
        Sid    = "EcsRelease"
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:DescribeTasks",
          "ecs:RegisterTaskDefinition", "ecs:RunTask", "ecs:UpdateService", "ecs:ListTasks",
        ]
        Resource = "*" # ECS describe/register calls do not support resource-level restriction
      },
      {
        Sid      = "PassTaskRoles"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
      },
      {
        Sid      = "ReadMigrationLogs"
        Effect   = "Allow"
        Action   = ["logs:GetLogEvents", "logs:DescribeLogStreams"]
        Resource = "${aws_cloudwatch_log_group.app.arn}:*"
      },
    ]
  })
}

# ============================================================== CloudFront ====
# Phase 6: "Console served over HTTPS". CloudFront fronts the HTTP ALB with a free TLS
# certificate on *.cloudfront.net. Caching is DISABLED: the console is live state and the
# API must never be served stale. CloudFront here is a TLS terminator, not a cache.
# COST: free tier 1 TB/month egress; demo traffic is well inside it (≈ USD 0).
# NOTE: the distribution's hostname changes on every rebuild — the frontend/IdP redirect
# URI must be updated after a Phase 7 restore (deployment-brief.md).

locals {
  # AWS managed policies (IDs are global constants, see CloudFront docs).
  cf_cache_policy_caching_disabled = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  cf_origin_request_all_viewer     = "216adef6-5c7f-47e4-b989-5492eafa07d3"
}

resource "aws_cloudfront_distribution" "console" {
  enabled         = true
  comment         = "${local.name} console (TLS in front of HTTP ALB, no caching)"
  price_class     = "PriceClass_200" # includes India; cheaper than all edges
  is_ipv6_enabled = true

  origin {
    origin_id   = "alb"
    domain_name = aws_lb.main.dns_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # ALB has no certificate (see ALB decision)
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60 # WebSocket /ws/telemetry idles up to 15 s between pings
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = local.cf_cache_policy_caching_disabled
    origin_request_policy_id = local.cf_origin_request_all_viewer # forwards Authorization + WebSocket headers
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # *.cloudfront.net, free, no domain needed
  }
}
