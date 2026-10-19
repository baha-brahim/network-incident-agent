variable "region" {
  description = "AWS region of every resource."
  type        = string
  default     = "eu-north-1"
}

variable "github_deploy" {
  description = "Create the GitHub OIDC provider and deploy role for the deploy workflow."
  type        = bool
  default     = true
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose main branch may deploy."
  type        = string
  default     = "baha-brahim/network-incident-agent"
}

variable "image_tag" {
  description = "Tag of the image the function is created with. Later deployments update the function directly and Terraform ignores the change."
  type        = string
  default     = "bootstrap"
}

variable "budget_email" {
  description = "Address that receives the AWS budget alerts."
  type        = string
}

# --- Function settings -------------------------------------------------------------------------

variable "database_url" {
  description = "Connection string of the API's database role (api_rw), pooled endpoint."
  type        = string
  sensitive   = true
}

variable "agent_database_url" {
  description = "Connection string of the read-only role (agent_ro) used by the agent's tools, pooled endpoint."
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
}

variable "groq_api_key" {
  type      = string
  sensitive = true
}

variable "alert_webhook_token" {
  description = "Bearer token of the alert webhook. Empty switches the webhook off."
  type        = string
  default     = ""
  sensitive   = true
}

variable "client_hash_salt" {
  description = "Salt of the hash that tells visitors apart for the per-client limit."
  type        = string
  sensitive   = true
}

variable "cors_origins" {
  description = "Web origins allowed to call the API."
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "live_enabled" {
  description = "Switch live investigations on or off. Recorded replays always work."
  type        = bool
  default     = true
}

variable "live_daily_limit" {
  type    = number
  default = 20
}

variable "live_per_client_daily_limit" {
  type    = number
  default = 3
}

variable "alert_daily_limit" {
  type    = number
  default = 10
}

variable "fallback_models" {
  description = "Models tried after the agent model fails. No local model server exists on Lambda."
  type        = list(string)
  default     = ["gemini:gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b"]
}
