#!/bin/bash
# Creates everything on AWS: chat-history S3 bucket, S3 Vectors bucket + index, EC2 IAM role.
# Run in AWS CloudShell from the project folder:
#   BUCKET=amanda-rag-chat-history-12345 VECTOR_BUCKET=amanda-rag-vectors REGION=eu-central-1 ./infra/setup-aws.sh
set -euo pipefail
: "${BUCKET:?Set BUCKET (globally unique name for chat history)}"
: "${VECTOR_BUCKET:?Set VECTOR_BUCKET (name for the S3 vector bucket)}"
REGION="${REGION:-eu-central-1}"
INDEX="${INDEX:-documents}"
DIM="${DIM:-1536}"
ROLE=rag-streamlit-ec2-role
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "1) Regular S3 bucket $BUCKET (chat history, private, encrypted, 7-day lifecycle)"
if [ "$REGION" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
  --lifecycle-configuration file://infra/s3-lifecycle.json

echo "2) S3 vector bucket $VECTOR_BUCKET + index $INDEX ($DIM dims, cosine)"
aws s3vectors create-vector-bucket --vector-bucket-name "$VECTOR_BUCKET" --region "$REGION"
aws s3vectors create-index --vector-bucket-name "$VECTOR_BUCKET" --index-name "$INDEX" \
  --data-type float32 --dimension "$DIM" --distance-metric cosine \
  --metadata-configuration '{"nonFilterableMetadataKeys":["content"]}' --region "$REGION"

echo "3) IAM role + instance profile for EC2 (no access keys on the server)"
sed -e "s/BUCKET_NAME/$BUCKET/g" -e "s/VECTOR_BUCKET/$VECTOR_BUCKET/g" \
    -e "s/REGION/$REGION/g" -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" \
    infra/ec2-s3-policy.template.json > /tmp/ec2-s3-policy.json
aws iam create-role --role-name "$ROLE" \
  --assume-role-policy-document file://infra/ec2-trust-policy.json >/dev/null
aws iam put-role-policy --role-name "$ROLE" --policy-name rag-s3-access \
  --policy-document file:///tmp/ec2-s3-policy.json
aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"

echo "Done. When launching EC2, choose IAM instance profile: $ROLE"
