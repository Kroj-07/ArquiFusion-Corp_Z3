variable "project_id" {
  description = "Google Cloud project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Cloud Run and Vertex AI region."
  type        = string
  default     = "us-central1"
}

variable "dataset_location" {
  description = "BigQuery multi-region location."
  type        = string
  default     = "US"
}

variable "container_image" {
  description = "Published Part B container image in Artifact Registry."
  type        = string
  default     = ""
}

variable "deploy_service" {
  description = "Create Cloud Run only after both Secret Manager versions and the image exist."
  type        = bool
  default     = false
}

variable "aws_api_base" {
  description = "Base HTTPS URL of the AWS API; do not include /v1."
  type        = string
}

variable "allow_public_signed_api" {
  description = "Allow public HTTPS invocation; API routes still require the shared HMAC signature."
  type        = bool
  default     = true
}
