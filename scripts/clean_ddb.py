
import boto3
import os

def clean_table(table_name):
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    
    print(f"Scanning table {table_name}...")
    scan = table.scan()
    
    with table.batch_writer() as batch:
        for each in scan.get("Items", []):
            print(f"Deleting job: {each['jobId']}")
            batch.delete_item(Key={"jobId": each["jobId"]})

    print("Table cleaned.")

if __name__ == "__main__":
    # Hardcoding or fetching from env if possible, but for now specific to this env
    # Using the table name from previous context
    TABLE_NAME = "podcast-transcription-jobs"
    clean_table(TABLE_NAME)
