# backend.tf — remote state for the DC-North AIOps infrastructure.
#
# Why remote state: "Terraform state tracked" (backend-spec §2). State in S3 survives a
# `terraform destroy` of everything else and is what makes the Phase 7 rebuild repeatable.
# DynamoDB provides the state lock so two people (or a person and a workflow) cannot
# apply at the same time.
#
# ONE-TIME MANUAL BOOTSTRAP (the bucket and table cannot be created by the config they
# hold state for). Run once per AWS account, with an admin profile, then never again:
#
#   export AWS_REGION=ap-south-1
#   export TF_STATE_BUCKET=dc-aiops-tfstate-<account-id>      # must be globally unique
#   aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION" \
#       --create-bucket-configuration LocationConstraint="$AWS_REGION"
#   aws s3api put-bucket-versioning --bucket "$TF_STATE_BUCKET" \
#       --versioning-configuration Status=Enabled
#   aws s3api put-public-access-block --bucket "$TF_STATE_BUCKET" \
#       --public-access-block-configuration \
#       BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
#   aws dynamodb create-table --table-name dc-aiops-tflock \
#       --attribute-definitions AttributeName=LockID,AttributeType=S \
#       --key-schema AttributeName=LockID,KeyType=HASH \
#       --billing-mode PAY_PER_REQUEST
#
# Then initialise with the bucket name (backend blocks cannot read variables):
#
#   cd deploy/terraform
#   terraform init -backend-config="bucket=$TF_STATE_BUCKET"
#
# Cost: S3 (a few KB) and DynamoDB on-demand are effectively free (< USD 1/month).
# These two resources are deliberately NOT part of `terraform destroy` — see
# deploy/deployment-brief.md, "what survives teardown".

terraform {
  backend "s3" {
    # bucket is supplied at init time: terraform init -backend-config="bucket=..."
    key            = "dc-aiops/production/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "dc-aiops-tflock"
    encrypt        = true
  }
}
