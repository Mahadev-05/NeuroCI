# ═══════════════════════════════════════════════════════════
# NeuroCI — Terraform Main Configuration
#
# Provisions NeuroCI infrastructure on GCP or AWS.
# Supports multi-provider LLM: Gemini, Groq, Ollama, OpenAI.
#
# Usage:
#   terraform init
#   terraform plan -var-file=terraform.tfvars
#   terraform apply -var-file=terraform.tfvars
# ═══════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ── GCP Provider ──
provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# ── AWS Provider ──
provider "aws" {
  region = var.aws_region
}

# ── Local: LLM environment variables (provider-agnostic) ──
locals {
  llm_env_vars = concat(
    [
      { name = "LLM_PROVIDER", value = var.llm_provider },
    ],
    var.llm_provider == "gemini" ? [
      { name = "GEMINI_API_KEY", value = var.gemini_api_key },
    ] : [],
    var.llm_provider == "groq" ? [
      { name = "GROQ_API_KEY", value = var.groq_api_key },
    ] : [],
    var.llm_provider == "openai" ? [
      { name = "OPENAI_API_KEY", value = var.openai_api_key },
    ] : [],
  )

  # Flat map for GCP Cloud Run env blocks
  llm_env_map = { for e in local.llm_env_vars : e.name => e.value }
}

# ═══════════════════════════════════════════════════════════
# GCP — Cloud Run + Memorystore
# ═══════════════════════════════════════════════════════════

resource "google_cloud_run_v2_service" "neuroci_webhook" {
  count    = var.cloud_provider == "gcp" ? 1 : 0
  name     = "neuroci-webhook"
  location = var.gcp_region

  template {
    containers {
      image = var.docker_image

      ports {
        container_port = 8000
      }

      env {
        name  = "REDIS_URL"
        value = "redis://${google_redis_instance.neuroci[0].host}:6379/0"
      }
      env {
        name  = "GITHUB_TOKEN"
        value = var.github_token
      }
      env {
        name  = "GITHUB_WEBHOOK_SECRET"
        value = var.github_webhook_secret
      }
      env {
        name  = "SLACK_BOT_TOKEN"
        value = var.slack_bot_token
      }

      # LLM provider config
      env {
        name  = "LLM_PROVIDER"
        value = var.llm_provider
      }

      dynamic "env" {
        for_each = var.llm_provider == "gemini" ? [1] : []
        content {
          name  = "GEMINI_API_KEY"
          value = var.gemini_api_key
        }
      }

      dynamic "env" {
        for_each = var.llm_provider == "groq" ? [1] : []
        content {
          name  = "GROQ_API_KEY"
          value = var.groq_api_key
        }
      }

      dynamic "env" {
        for_each = var.llm_provider == "openai" ? [1] : []
        content {
          name  = "OPENAI_API_KEY"
          value = var.openai_api_key
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }
  }
}

resource "google_redis_instance" "neuroci" {
  count          = var.cloud_provider == "gcp" ? 1 : 0
  name           = "neuroci-redis"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.gcp_region
  redis_version  = "REDIS_7_0"
}

# ═══════════════════════════════════════════════════════════
# AWS — ECS Fargate + ElastiCache
# ═══════════════════════════════════════════════════════════

resource "aws_ecs_cluster" "neuroci" {
  count = var.cloud_provider == "aws" ? 1 : 0
  name  = "neuroci"
}

resource "aws_ecs_task_definition" "neuroci_webhook" {
  count                    = var.cloud_provider == "aws" ? 1 : 0
  family                   = "neuroci-webhook"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "neuroci-webhook"
      image     = var.docker_image
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = concat(
        [
          { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.neuroci[0].cache_nodes[0].address}:6379/0" },
          { name = "GITHUB_TOKEN", value = var.github_token },
          { name = "GITHUB_WEBHOOK_SECRET", value = var.github_webhook_secret },
          { name = "SLACK_BOT_TOKEN", value = var.slack_bot_token },
          { name = "LLM_PROVIDER", value = var.llm_provider },
        ],
        local.llm_env_vars,
      )
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/neuroci"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "webhook"
        }
      }
    }
  ])
}

resource "aws_elasticache_cluster" "neuroci" {
  count                = var.cloud_provider == "aws" ? 1 : 0
  cluster_id           = "neuroci-redis"
  engine               = "redis"
  engine_version       = "7.0"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
}
