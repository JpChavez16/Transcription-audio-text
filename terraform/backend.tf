terraform {
  backend "s3" {
    bucket = "podcast-transcription-tfstate-944130632329"
    key    = "terraform.tfstate"
    region = "us-east-1"

    # Descomentar después de crear el bucket
    # dynamodb_table = "terraform-state-lock"
  }
}
