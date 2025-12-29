#!/bin/bash

PROJECT_TAG="podcast-transcription"
REGION="us-east-1"

echo "☢️  STARTING NUCLEAR CLEANUP FOR PROJECT: $PROJECT_TAG ☢️"

# ==========================================
# 1. DELETE LOAD BALANCERS & TARGET GROUPS
# ==========================================
echo "🔍 Checking Load Balancers..."
LBS=$(aws elbv2 describe-load-balancers --region $REGION --query "LoadBalancers[?contains(LoadBalancerName, '$PROJECT_TAG')].LoadBalancerArn" --output text)
for LB in $LBS; do
    echo "Deleting LB: $LB"
    aws elbv2 delete-load-balancer --load-balancer-arn $LB --region $REGION
done

echo "🔍 Checking Target Groups..."
TGS=$(aws elbv2 describe-target-groups --region $REGION --query "TargetGroups[?contains(TargetGroupName, '$PROJECT_TAG')].TargetGroupArn" --output text)
for TG in $TGS; do
    echo "Deleting TG: $TG"
    aws elbv2 delete-target-group --target-group-arn $TG --region $REGION
done

# ==========================================
# 2. DELETE ECS CLUSTERS
# ==========================================
echo "🔍 Checking ECS Clusters..."
CLUSTERS=$(aws ecs list-clusters --region $REGION --query "clusterArns[]" --output text)
for CLUSTER in $CLUSTERS; do
    if [[ $CLUSTER == *"$PROJECT_TAG"* ]]; then
        echo "Processing Cluster: $CLUSTER"
        
        # Stop Tasks
        TASKS=$(aws ecs list-tasks --cluster $CLUSTER --region $REGION --query "taskArns[]" --output text)
        for TASK in $TASKS; do
            aws ecs stop-task --cluster $CLUSTER --task $TASK --region $REGION > /dev/null
        done
        
        # Delete Services
        SERVICES=$(aws ecs list-services --cluster $CLUSTER --region $REGION --query "serviceArns[]" --output text)
        for SERVICE in $SERVICES; do
            aws ecs delete-service --cluster $CLUSTER --service $SERVICE --force --region $REGION > /dev/null
        done
        
        # Delete Cluster
        aws ecs delete-cluster --cluster $CLUSTER --region $REGION
        echo "✅ Deleted Cluster: $CLUSTER"
    fi
done

# ==========================================
# 3. DELETE ECR REPOSITORIES
# ==========================================
echo "🔍 Checking ECR Repositories..."
REPOS=$(aws ecr describe-repositories --region $REGION --query "repositories[?contains(repositoryName, '$PROJECT_TAG')].repositoryName" --output text)
for REPO in $REPOS; do
    echo "Deleting ECR Repo: $REPO"
    aws ecr delete-repository --repository-name $REPO --force --region $REGION > /dev/null
done

# ==========================================
# 4. DELETE LAMBDA FUNCTIONS
# ==========================================
echo "🔍 Checking Lambda Functions..."
LAMBDAS=$(aws lambda list-functions --region $REGION --query "Functions[?contains(FunctionName, '$PROJECT_TAG')].FunctionName" --output text)
for LAMBDA in $LAMBDAS; do
    echo "Deleting Lambda: $LAMBDA"
    aws lambda delete-function --function-name $LAMBDA --region $REGION
done

# ==========================================
# 5. DELETE DYNAMODB TABLES
# ==========================================
echo "🔍 Checking DynamoDB Tables..."
TABLES=$(aws dynamodb list-tables --region $REGION --query "TableNames[]" --output text)
for TABLE in $TABLES; do
    if [[ $TABLE == *"$PROJECT_TAG"* ]]; then
        echo "Deleting Table: $TABLE"
        aws dynamodb delete-table --table-name $TABLE --region $REGION > /dev/null
    fi
done

# ==========================================
# 6. DELETE S3 BUCKETS
# ==========================================
echo "🔍 Checking S3 Buckets..."
BUCKETS=$(aws s3api list-buckets --query "Buckets[?contains(Name, '$PROJECT_TAG')].Name" --output text)
for BUCKET in $BUCKETS; do
    echo "Deleting Bucket: $BUCKET"
    aws s3 rb s3://$BUCKET --force > /dev/null
done

# ==========================================
# 7. DELETE VPCs & NETWORKING (The Hard Part)
# ==========================================
echo "🔍 Checking VPCs..."
VPCS=$(aws ec2 describe-vpcs --filters "Name=tag:Project,Values=$PROJECT_TAG" --region $REGION --query "Vpcs[].VpcId" --output text)

for VPC in $VPCS; do
    echo "Processing VPC: $VPC"

    # Delete Nat Gateways
    NAT_GWS=$(aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$VPC" --region $REGION --query "NatGateways[].NatGatewayId" --output text)
    for NAT in $NAT_GWS; do
        echo "  Deleting NAT Gateway: $NAT"
        aws ec2 delete-nat-gateway --nat-gateway-id $NAT --region $REGION > /dev/null
        # Wait for deletion
        echo "  Waiting for NAT deletion..."
        aws ec2 wait nat-gateway-deleted --nat-gateway-ids $NAT --region $REGION
    done

    # Detach & Delete IGWs
    IGWS=$(aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC" --region $REGION --query "InternetGateways[].InternetGatewayId" --output text)
    for IGW in $IGWS; do
        echo "  Detaching IGW: $IGW"
        aws ec2 detach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC --region $REGION
        echo "  Deleting IGW: $IGW"
        aws ec2 delete-internet-gateway --internet-gateway-id $IGW --region $REGION
    done

    # Delete Subnets
    SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --region $REGION --query "Subnets[].SubnetId" --output text)
    for SUBNET in $SUBNETS; do
        echo "  Deleting Subnet: $SUBNET"
        aws ec2 delete-subnet --subnet-id $SUBNET --region $REGION
    done

    # Delete Security Groups (except default)
    SGS=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" --region $REGION --query "SecurityGroups[?GroupName!='default'].GroupId" --output text)
    for SG in $SGS; do
        echo "  Deleting Security Group: $SG"
        aws ec2 delete-security-group --group-id $SG --region $REGION
    done

    # Delete VPC
    echo "Deleting VPC: $VPC"
    aws ec2 delete-vpc --vpc-id $VPC --region $REGION
done

# ==========================================
# 8. DELETE IAM ROLES
# ==========================================
echo "🔍 Checking IAM Roles..."
ROLES=$(aws iam list-roles --query "Roles[?contains(RoleName, '$PROJECT_TAG')].RoleName" --output text)
for ROLE in $ROLES; do
    echo "Processing Role: $ROLE"
    # Detach Policies first
    POLICIES=$(aws iam list-attached-role-policies --role-name $ROLE --query "AttachedPolicies[].PolicyArn" --output text)
    for POLICY in $POLICIES; do
        aws iam detach-role-policy --role-name $ROLE --policy-arn $POLICY
    done
    
    # Delete Inline Policies
    INLINE=$(aws iam list-role-policies --role-name $ROLE --query "PolicyNames[]" --output text)
    for POLICY in $INLINE; do
        aws iam delete-role-policy --role-name $ROLE --policy-name $POLICY
    done
    
    # Delete Role
    aws iam delete-role --role-name $ROLE
    echo "✅ Deleted Role: $ROLE"
done

echo "✅ CLEANUP COMPLETE"
