# NeuroCI — Terraform Variables

variable "cloud_provider" {
  description = "Cloud provider to deploy on: gcp or aws"
  type        = string
  default     = "gcp"
  validation {
    condition     = contains(["gcp", "aws"], var.cloud_provider)
    error_message = "cloud_provider must be 'gcp' or 'aws'"
  }
}

variable "docker_image" {
  description = "NeuroCI Docker image URI"
  type        = string
  default     = "neuroci:latest"
}

# ── GCP ──
variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
  default     = ""
}

variable "gcp_region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

# ── AWS ──
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# ── Secrets ──
variable "github_token" {
  description = "GitHub personal access token"
  type        = string
  sensitive   = true
}

variable "github_webhook_secret" {
  description = "GitHub webhook HMAC secret"
  type        = string
  sensitive   = true
}

variable "slack_bot_token" {
  description = "Slack bot OAuth token"
  type        = string
  sensitive   = true
  default     = ""
}

# ── LLM Provider Configuration ──
variable "llm_provider" {
  description = "LLM provider: gemini (free), groq (free), ollama (local), openai (paid)"
  type        = string
  default     = "gemini"
  validation {
    condition     = contains(["gemini", "groq", "ollama", "openai"], var.llm_provider)
    error_message = "llm_provider must be one of: gemini, groq, ollama, openai"
  }
}

variable "gemini_api_key" {
  description = "Google Gemini API key (free at aistudio.google.com)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "groq_api_key" {
  description = "Groq API key (free at console.groq.com)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openai_api_key" {
  description = "OpenAI API key (paid)"
  type        = string
  sensitive   = true
  default     = ""
}
