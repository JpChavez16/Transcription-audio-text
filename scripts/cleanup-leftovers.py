import boto3
import time
import sys

# Configuration
PROJECT_TAG = "podcast-transcription"
REGION = "us-east-1"

# Initialize Clients
s3 = boto3.resource('s3', region_name=REGION)
ec2 = boto3.resource('ec2', region_name=REGION)
ec2_client = boto3.client('ec2', region_name=REGION)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def nuke_buckets():
    log("🗑️  Scanning for S3 Buckets...")
    for bucket in s3.buckets.all():
        if PROJECT_TAG in bucket.name:
            log(f"Processing Bucket: {bucket.name}")
            try:
                # Delete all object versions (handles both objects and delete markers)
                log("   - Deleting object versions...")
                bucket.object_versions.delete()
                
                # Delete bucket
                log("   - Deleting bucket...")
                bucket.delete()
                log("   ✅ Bucket deleted.")
            except Exception as e:
                log(f"   ❌ Failed to delete bucket: {e}")

def nuke_vpcs():
    log("🗑️  Scanning for VPCs...")
    # Find VPCs by Tag
    filters = [{'Name': 'tag:Project', 'Values': [PROJECT_TAG]}]
    vpcs = list(ec2.vpcs.filter(Filters=filters))
    
    if not vpcs:
        log("   ℹ️  No VPCs found with project tag.")
        return

    for vpc in vpcs:
        log(f"Processing VPC: {vpc.id}")
        
        # 1. Delete Dependencies: Network Interfaces (ENIs)
        log("   - Cleaning up Network Interfaces...")
        for eni in vpc.network_interfaces.all():
            try:
                log(f"     - Detaching/Deleting ENI: {eni.id} ({eni.description})")
                if eni.attachment:
                    eni.detach()
                eni.delete()
            except Exception as e:
                log(f"       ⚠️  Could not delete ENI {eni.id}: {e}")

        # 2. Delete Dependencies: Internet Gateways
        for igw in vpc.internet_gateways.all():
            log(f"   - Deleting IGW: {igw.id}")
            igw.detach_from_vpc(VpcId=vpc.id)
            igw.delete()

        # 3. Delete Dependencies: Subnets
        for subnet in vpc.subnets.all():
            log(f"   - Deleting Subnet: {subnet.id}")
            try:
                subnet.delete()
            except Exception as e:
                log(f"       ❌ Failed to delete subnet: {e}")

        # 4. Delete Dependencies: Security Groups
        for sg in vpc.security_groups.all():
            if sg.group_name != 'default':
                log(f"   - Deleting SG: {sg.id}")
                try:
                    sg.delete()
                except Exception as e:
                    log(f"       ❌ Failed to delete SG: {e}")

        # 5. Delete VPC
        log(f"   - Deleting VPC: {vpc.id}")
        try:
            vpc.delete()
            log("   ✅ VPC deleted.")
        except Exception as e:
            log(f"   ❌ Failed to delete VPC: {e}")

if __name__ == "__main__":
    print(f"🔥 Starting Cleanup Phase 2 for: {PROJECT_TAG} 🔥")
    nuke_buckets()
    nuke_vpcs()
    print("✨ Cleanup Phase 2 Complete.")
