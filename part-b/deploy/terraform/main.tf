locals {
  apis = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "fleet" {
  dataset_id                 = "fleet"
  location                   = var.dataset_location
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "part_b" {
  location      = var.region
  repository_id = "arquifusion"
  description   = "ArquiFusion application images"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_service_account" "part_b" {
  account_id   = "af-part-b"
  display_name = "ArquiFusion Part B Cloud Run"
}

resource "google_project_iam_member" "bigquery_job" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.part_b.email}"
}

resource "google_bigquery_dataset_iam_member" "bigquery_data" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.fleet.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.part_b.email}"
}

resource "google_project_iam_member" "vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.part_b.email}"
}

resource "google_secret_manager_secret" "c_api_auth" {
  secret_id = "arquifusion-b-api-auth"
  replication { auto {} }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "alert_hmac" {
  secret_id = "arquifusion-alert-hmac"
  replication { auto {} }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "c_api_auth" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.c_api_auth.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.part_b.email}"
}

resource "google_secret_manager_secret_iam_member" "alert_hmac" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.alert_hmac.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.part_b.email}"
}

resource "google_cloud_run_v2_service" "part_b" {
  count               = var.deploy_service ? 1 : 0
  name                = "af-part-b"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true
  lifecycle {
    precondition {
      condition     = !var.deploy_service || length(trimspace(var.container_image)) > 0
      error_message = "Set container_image before creating the Cloud Run service."
    }
  }

  template {
    service_account = google_service_account.part_b.email
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
    containers {
      image = var.container_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "BIGQUERY_DATASET"
        value = google_bigquery_dataset.fleet.dataset_id
      }
      env {
        name  = "A_API_BASE"
        value = var.aws_api_base
      }
      env {
        name = "B_API_AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.c_api_auth.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "B_ALERT_HMAC_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.alert_hmac.secret_id
            version = "latest"
          }
        }
      }
    }
    depends_on = [
      google_secret_manager_secret_iam_member.c_api_auth,
      google_secret_manager_secret_iam_member.alert_hmac,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.part_b,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.deploy_service && var.allow_public_signed_api ? 1 : 0
  project  = var.project_id
  location = google_cloud_run_v2_service.part_b[0].location
  name     = google_cloud_run_v2_service.part_b[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value       = var.deploy_service ? google_cloud_run_v2_service.part_b[0].uri : null
  description = "HTTPS base URL consumed by Part C."
}

output "artifact_registry_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.part_b.repository_id}"
}

# --- Puente multi-nube A -> B: Pub/Sub telemetry-raw -> BigQuery fleet.telemetry --------------
# Contrato 6.12. La Lambda puente de A publica la telemetría ya APLANADA (part-a/bridge/
# pubsub_bridge/flatten.py) y esta suscripción la escribe en fleet.telemetry sin servidores.

resource "google_pubsub_topic" "telemetry_raw" {
  name       = "telemetry-raw"
  depends_on = [google_project_service.apis]
}

# Cuenta que usa la Lambda de A (clave JSON guardada SOLO en AWS Secrets Manager, ver
# scripts/set_secrets.sh). Permiso mínimo: publicar en este tópico. La clave NO se crea aquí
# para no dejar secretos en el estado de Terraform:
#   gcloud iam service-accounts keys create key.json --iam-account af-bridge-publisher@PROYECTO.iam.gserviceaccount.com
resource "google_service_account" "bridge_publisher" {
  account_id   = "af-bridge-publisher"
  display_name = "ArquiFusion AWS bridge (publish only)"
}

resource "google_pubsub_topic_iam_member" "bridge_publish" {
  topic  = google_pubsub_topic.telemetry_raw.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.bridge_publisher.email}"
}

data "google_project" "current" {
  project_id = var.project_id
}

# El agente de servicio de Pub/Sub escribe en BigQuery.
resource "google_bigquery_dataset_iam_member" "pubsub_agent_editor" {
  dataset_id = google_bigquery_dataset.fleet.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "pubsub_agent_metadata" {
  project = var.project_id
  role    = "roles/bigquery.metadataViewer"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# Se activa DESPUÉS de crear las tablas (part-b/bigquery/01_schema.sql): la suscripción exige
# que fleet.telemetry ya exista.
resource "google_pubsub_subscription" "telemetry_to_bigquery" {
  count = var.create_telemetry_subscription ? 1 : 0
  name  = "telemetry-raw-to-bigquery"
  topic = google_pubsub_topic.telemetry_raw.id

  bigquery_config {
    table               = "${var.project_id}.${google_bigquery_dataset.fleet.dataset_id}.telemetry"
    use_table_schema    = true
    drop_unknown_fields = true # tolera campos nuevos de A sin perder el mensaje
  }

  depends_on = [
    google_bigquery_dataset_iam_member.pubsub_agent_editor,
    google_project_iam_member.pubsub_agent_metadata,
  ]
}

output "pubsub_topic" {
  value       = google_pubsub_topic.telemetry_raw.name
  description = "Valor para SSM /arquifusion/{env}/bridge/pubsub-topic."
}

output "bridge_publisher_email" {
  value = google_service_account.bridge_publisher.email
}
