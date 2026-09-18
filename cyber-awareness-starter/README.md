# Cyber Awareness Platform

An internal FastAPI application for creating, revising, approving, scheduling,
and emailing cybersecurity infographic posters. Employees authenticate with
Microsoft Entra ID, Azure OpenAI creates the copy and PNG artwork, and Microsoft
Graph sends the current approved poster inline from a shared mailbox.

## What changed

- Azure OpenAI replaces Ollama and ComfyUI.
- A poster studio provides a persistent chat for every campaign.
- Each prompt creates a new saved PNG version; earlier versions remain viewable.
- Creating a campaign immediately starts its first poster generation without
  opening the studio.
- Campaign details are fixed after creation; poster changes are made only by
  prompting Azure OpenAI in the studio.
- Any AI revision clears approval and scheduling for safety.
- Sent campaigns are read-only.
- Approved campaigns can be sent immediately or scheduled using the employee's
  local date and time; the server stores and processes the time in UTC.
- Sent campaigns can be deleted from campaign history. Deleting the campaign
  does not recall email that has already been delivered.

## Run with Docker

1. Create the local settings file once:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Fill in `.env`. For a real Azure run, at minimum set:

   ```dotenv
   MOCK_AI_SERVICES=false
   MOCK_EMAIL_SERVICE=false
   DEV_AUTH_BYPASS=false

   AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/
   AZURE_OPENAI_TEXT_DEPLOYMENT=YOUR-TEXT-DEPLOYMENT-NAME
   AZURE_OPENAI_IMAGE_DEPLOYMENT=YOUR-GPT-IMAGE-DEPLOYMENT-NAME

   ENTRA_TENANT_ID=YOUR-TENANT-ID
   ENTRA_API_CLIENT_ID=YOUR-WEB-APP-CLIENT-ID
   ENTRA_CLIENT_SECRET=YOUR-WEB-APP-CLIENT-SECRET
   SESSION_SECRET=REPLACE-WITH-A-RANDOM-32-PLUS-CHARACTER-SECRET

   AZURE_TENANT_ID=YOUR-TENANT-ID
   AZURE_CLIENT_ID=YOUR-WORKLOAD-APP-CLIENT-ID
   AZURE_CLIENT_SECRET=YOUR-WORKLOAD-APP-CLIENT-SECRET
   GRAPH_SENDER_MAILBOX=securityawareness@your-company.com
   ```

   Leave `AZURE_OPENAI_API_KEY` blank to use the workload application's Entra
   identity. The same `AZURE_*` workload credentials are used by Graph and may
   also be used by Azure Database for PostgreSQL.

3. Start the application:

   ```powershell
   docker compose up --build -d
   ```

4. Open <http://localhost:8000>.

For later starts with unchanged dependencies, use:

```powershell
docker compose up -d
```

The Dockerfile copies dependencies before application code, so Docker can reuse
the slow dependency layer when only Python, HTML, or CSS changes.

## Development mode

The sample `.env.example` starts safely without Azure or email calls:

```dotenv
MOCK_AI_SERVICES=true
MOCK_EMAIL_SERVICE=true
DEV_AUTH_BYPASS=true
```

This creates placeholder poster images and records mock sends.

## Poster workflow

1. Complete the campaign form. The signed-in employee becomes `created_by`.
2. Select **Create and generate poster**. The campaign list shows
   **Waiting to generate** while Azure OpenAI creates the first PNG.
3. When generation finishes, open the poster studio to review the image.
4. Use only the studio chat to request changes, such as “Make the title shorter
   and use five centered sections.”
5. Each prompt creates a new saved version and clears prior approval/scheduling.
6. Approve the current version, then either send it immediately or choose a
   future date and time with **Schedule send**.
7. A scheduled campaign can be cancelled with **Unapprove** before the worker
   begins sending it.

Topic, audience, and initial creative direction cannot be edited after
creation. Recipient emails can be changed until sending begins; changing them
clears approval and any schedule so the campaign must be approved again.
Poster chat history and all generated versions are stored in the database.

## Azure OpenAI requirements

- Deploy one supported text model with structured-output support.
- Deploy a `gpt-image-*` model that supports both generation and image editing.
- Put the deployment names—not merely the model family names—in `.env`.
- Give the workload service principal permission to invoke the Azure OpenAI
  resource, or provide an API key for local testing.

See [AZURE_SETUP.md](AZURE_SETUP.md) for configuration details.

## Storage

- Campaigns, messages, version metadata, approvals, and audits: SQL database.
- PNG poster versions: `generated_posters/` locally or its Docker bind mount.
- PostgreSQL container data: the `postgres_data` Docker volume.

For production, replace local poster storage with Azure Blob Storage and store
secrets in Key Vault or deployment-time secret settings.

## Useful commands

```powershell
# Logs
docker compose logs -f app

# Restart after code changes
docker compose up --build -d app

# Run tests inside the image
docker compose run --rm app pip install pytest
docker compose run --rm app pytest

# Stop without deleting data
docker compose down

# Delete the local PostgreSQL volume and all database data
docker compose down -v
```

Do not run `docker compose down -v` against data you need to retain.
