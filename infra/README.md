# Deploying the API

The API runs as one AWS Lambda function (a container image with the Lambda Web Adapter, response
streaming on, behind a public function URL) in `eu-central-1`. The data lives in a Neon Postgres
project in the same region, and the web interface runs on Vercel. A GitHub Actions workflow
(`.github/workflows/deploy.yml`) ships every green push to `main`.

```
Vercel (frontend/)  --->  Lambda function URL  --->  Neon (pooled endpoint)
                              |  image in ECR
                              +--> Gemini / Groq
```

## Cost rules

- Use only always-free services: Lambda, the function URL, IAM, CloudWatch Logs (7-day retention)
  and one AWS Budget. Create no NAT gateway, VPC, load balancer, API Gateway, Secrets Manager
  secret, KMS key, S3 bucket, RDS or CloudFront. Terraform state stays on this machine.
- ECR storage is the only item that can cost cents: one repository that keeps its 2 newest images.
  A budget of 1 USD a month mails an alert at 50% actual and 100% forecast spend.

## What is where

| Piece | File |
|---|---|
| Image | `backend/Dockerfile`, `backend/.dockerignore` |
| Infrastructure | `infra/terraform/` (ECR, function, function URL, logs, GitHub deploy role, budget) |
| Database publish | `backend/src/incident_agent/db/publish.py` |
| Continuous deployment | `.github/workflows/deploy.yml` |

## Local check of the image

The function's file system is read-only except `/tmp`, so test the image the same way. With the
local database running (`docker compose up -d`) and migrated (`uv run alembic upgrade head` from
`backend/`; a database one migration behind answers `/api/meta` with 503):

```
docker build -t incident-agent-api:local backend
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 -e DATABASE_URL=postgresql://incident:incident@host.docker.internal:5433/incident_agent -e AGENT_DATABASE_URL=postgresql://agent_ro:agent_ro@host.docker.internal:5433/incident_agent -e LIVE_ENABLED=false incident-agent-api:local
```

Then, from another terminal:

```
curl http://localhost:8080/api/ping
curl http://localhost:8080/api/meta
curl http://localhost:8080/api/demos
curl -N -X POST "http://localhost:8080/api/demos/fiber-cut/stream?speed=20"
```

All four answer; the last one streams a recorded investigation without calling a model. The image
holds the embedding model, so a cold start downloads nothing.

## First-time setup

You need an AWS account, the AWS CLI with credentials that can create the resources below (kept in
your AWS profile, never in this repository), Terraform 1.9 or newer, Docker, and a GitHub
repository.

1. **Neon.** Create a project in `eu-central-1` (Postgres 18). Copy the **direct** connection
   string (the host has no `-pooler`) into `.env` as `NEON_DATABASE_URL`. Also put two long random
   passwords for the application roles into `.env` as `AGENT_RO_PASSWORD` and `API_RW_PASSWORD`,
   and a random `CLIENT_HASH_SALT`.
2. **Load the data.** From `backend/`:

   ```
   uv run python -m incident_agent.db.publish --target-env NEON_DATABASE_URL --dry-run
   uv run python -m incident_agent.db.publish --target-env NEON_DATABASE_URL
   ```

   This migrates the target, creates the roles `agent_ro` (read `public`) and `api_rw` (read
   `public`, read and write `app`), copies the network data from the local database and compares
   row counts. Neither role can read the ground-truth schema. It can be repeated; it empties and
   refills the data tables each time.
3. **Variables.** In `infra/terraform/`, copy `terraform.tfvars.example` to `terraform.tfvars`
   (git-ignored) and fill it in. `database_url` and `agent_database_url` are the **pooled**
   connection strings (host contains `-pooler`) for `api_rw` and `agent_ro`.
4. **Create the registry first.**

   ```
   terraform init
   terraform apply -target=aws_ecr_repository.api -target=aws_ecr_lifecycle_policy.api -target=aws_ecr_repository_policy.lambda_pull
   ```

5. **Push a first image.** The function cannot be created without one. Build without
   attestations, because Lambda rejects the image index they create:

   ```
   aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com
   docker build --platform linux/amd64 --provenance=false -t ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com/incident-agent-api:bootstrap backend
   docker push ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com/incident-agent-api:bootstrap
   ```

6. **Create the rest.** `terraform apply`. The outputs give `function_url`, `ecr_repository_url`
   and `deploy_role_arn`. Check the function: `curl FUNCTION_URL/api/ping`. An account can hold
   only one GitHub OIDC provider; if it already has one, import it with
   `terraform import aws_iam_openid_connect_provider.github PROVIDER_ARN` before applying.
7. **Web interface.** Import the repository in Vercel with root directory `frontend/` and the
   environment variable `NEXT_PUBLIC_API_URL` set to the function URL. Add the Vercel address to
   `cors_origins` in `terraform.tfvars` and run `terraform apply` again.
8. **Continuous deployment.** In the GitHub repository, under Settings, Secrets and variables,
   Actions, Variables, add `AWS_DEPLOY_ROLE_ARN` (the `deploy_role_arn` output) and `API_URL` (the
   function URL). From then on every green push to `main` builds the image, pushes it tagged with
   the commit, updates the function and checks `/api/ping` and `/api/demos`. The workflow can also
   be started by hand from the Actions tab.

## Changing settings

Edit `terraform.tfvars` and run `terraform apply`. It updates the function's environment and
leaves the image alone (the deploy workflow owns the image). `live_enabled = false` switches live
investigations off; recorded replays keep working.

## Limits on live investigations

A visitor is identified by the first address in the `X-Forwarded-For` header, stored only as a
salted hash. The defaults are 3 live investigations per visitor and 20 in total per UTC day
(`live_per_client_daily_limit`, `live_daily_limit`). Alert-triggered runs have their own daily
limit (`alert_daily_limit`).

## Rollback

Point the function at an earlier image (the registry keeps the newest two):

```
aws ecr describe-images --repository-name incident-agent-api --query "sort_by(imageDetails,&imagePushedAt)[].imageTags"
aws lambda update-function-code --function-name incident-agent-api --image-uri ACCOUNT_ID.dkr.ecr.eu-central-1.amazonaws.com/incident-agent-api:COMMIT_SHA
aws lambda wait function-updated --function-name incident-agent-api
```

A rollback of the image does not undo database migrations, so keep them additive: the previous
image must keep working against the newer schema.

## Teardown

`terraform destroy` removes the function, URL, logs, roles, registry (with its images) and budget.
Delete the Neon project in its console.
