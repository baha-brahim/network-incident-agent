data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  name               = "${local.name}-function"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "function_logs" {
  role       = aws_iam_role.function.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 7
}

locals {
  # Empty values are left out, so the application sees them as unset.
  environment = {
    DATABASE_URL                = var.database_url
    AGENT_DATABASE_URL          = var.agent_database_url
    GEMINI_API_KEY              = var.gemini_api_key
    GROQ_API_KEY                = var.groq_api_key
    ALERT_WEBHOOK_TOKEN         = var.alert_webhook_token
    CLIENT_HASH_SALT            = var.client_hash_salt
    CORS_ORIGINS                = jsonencode(var.cors_origins)
    LIVE_ENABLED                = tostring(var.live_enabled)
    LIVE_DAILY_LIMIT            = tostring(var.live_daily_limit)
    LIVE_PER_CLIENT_DAILY_LIMIT = tostring(var.live_per_client_daily_limit)
    ALERT_DAILY_LIMIT           = tostring(var.alert_daily_limit)
    FALLBACK_MODELS             = jsonencode(var.fallback_models)
  }
}

resource "aws_lambda_function" "api" {
  function_name = local.name
  role          = aws_iam_role.function.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = 1536
  timeout       = 180

  ephemeral_storage {
    size = 512
  }

  environment {
    variables = { for name, value in local.environment : name => value if value != "" }
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy_attachment.function_logs,
    aws_ecr_repository_policy.lambda_pull,
  ]

  lifecycle {
    # The CD workflow updates the image; Terraform must not move it back.
    ignore_changes = [image_uri]
  }
}

# CORS is handled by the application, so the URL itself has no CORS block.
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"
  invoke_mode        = "RESPONSE_STREAM"
}

# A public function URL needs both permissions.
resource "aws_lambda_permission" "url_public" {
  statement_id           = "FunctionURLAllowPublicAccess"
  function_name          = aws_lambda_function.api.function_name
  action                 = "lambda:InvokeFunctionUrl"
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "FunctionURLInvokeAllowPublicAccess"
  function_name            = aws_lambda_function.api.function_name
  action                   = "lambda:InvokeFunction"
  principal                = "*"
  invoked_via_function_url = true
}
