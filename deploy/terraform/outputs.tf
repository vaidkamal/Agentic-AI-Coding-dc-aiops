# outputs.tf — the values the workflow, the scripts and the frontend need.
# After `terraform apply`, copy these into GitHub (Settings → Secrets and variables):
#   secrets:   AWS_DEPLOY_ROLE_ARN = deploy_role_arn,  ALB_URL = alb_url
#   variables: AWS_REGION, ECR_REPOSITORY, ECS_CLUSTER, ECS_SERVICE
# deploy/scripts/*.sh read them with `terraform output -raw <name>`.

output "alb_url" {
  description = "HTTP URL of the load balancer (deploy workflow health check + smoke test)"
  value       = "http://${aws_lb.main.dns_name}"
}

output "console_url" {
  description = "HTTPS URL for operators (Phase 6). Changes on every rebuild."
  value       = "https://${aws_cloudfront_distribution.console.domain_name}"
}

output "ecr_repository" {
  description = "ECR repository name (GitHub variable ECR_REPOSITORY)"
  value       = aws_ecr_repository.app.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecs_cluster" {
  description = "GitHub variable ECS_CLUSTER"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service" {
  description = "GitHub variable ECS_SERVICE"
  value       = aws_ecs_service.api.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.api.family
}

output "rds_identifier" {
  description = "DB instance identifier; backup.sh snapshots this"
  value       = aws_db_instance.main.identifier
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN injected into the task as DATABASE_URL"
  value       = aws_secretsmanager_secret.database_url.arn
}

output "deploy_role_arn" {
  description = "GitHub secret AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.github_deploy.arn
}

output "aws_region" {
  description = "GitHub variable AWS_REGION"
  value       = var.aws_region
}

output "private_subnet_ids" {
  description = "Where the one-off migration task runs (deploy.yml copies the service's network config instead, but handy for manual runs)"
  value       = aws_subnet.private[*].id
}

output "ecs_security_group_id" {
  value = aws_security_group.ecs.id
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}
