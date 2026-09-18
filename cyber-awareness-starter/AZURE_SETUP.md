# Azure setup

This application uses three separate Azure capabilities:

1. Microsoft Entra ID user login for Megawide employees.
2. A workload identity for Azure OpenAI, Microsoft Graph, and optionally Azure
   Database for PostgreSQL.
3. Azure OpenAI text and image deployments.

No application roles are required. Every valid employee in the tenant can sign
in, and the app records the signed-in user's email in `created_by`.

## 1. Employee login app registration

In **Microsoft Entra admin center → App registrations**, create or open the web
application registration.

- Supported account type: accounts in this organizational directory only.
- Platform: Web.
- Redirect URI for local testing: `http://localhost:8000/auth/callback`.
- Front-channel logout is optional.
- Create a client secret for server-side sign-in.
- Do not define App Roles.

Set:

```dotenv
ENTRA_TENANT_ID=tenant-guid
ENTRA_API_CLIENT_ID=login-app-client-guid
ENTRA_CLIENT_SECRET=login-app-secret
ENTRA_REDIRECT_URI=http://localhost:8000/auth/callback
ENTRA_POST_LOGOUT_REDIRECT_URI=http://localhost:8000/
SESSION_SECRET=a-random-secret-at-least-32-characters-long
SESSION_COOKIE_SECURE=false
DEV_AUTH_BYPASS=false
```

For HTTPS production, use the production callback URLs and set
`SESSION_COOKIE_SECURE=true`.

## 2. Workload app registration

Create a second app registration for background service access. This identity is
not used for employee login.

Set:

```dotenv
AZURE_TENANT_ID=tenant-guid
AZURE_CLIENT_ID=workload-app-client-guid
AZURE_CLIENT_SECRET=workload-app-secret
```

The code loads these values through `DefaultAzureCredential`.

## 3. Azure OpenAI

In the Azure portal or Microsoft Foundry portal:

1. Open the Azure OpenAI resource.
2. Deploy a text model that supports structured JSON output.
3. Deploy a `gpt-image-*` model that supports image generation and editing.
4. Record each **deployment name**.
5. In the Azure OpenAI resource's **Access control (IAM)**, assign an Azure AI/
   Cognitive Services inference user role supported by that resource to the
   workload application's service principal.

Use the exact endpoint shown under **Keys and Endpoint**:

```dotenv
AZURE_OPENAI_ENDPOINT=https://resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_TEXT_DEPLOYMENT=exact-text-deployment-name
AZURE_OPENAI_IMAGE_DEPLOYMENT=exact-image-deployment-name
AZURE_OPENAI_IMAGE_SIZE=1024x1536
AZURE_OPENAI_IMAGE_QUALITY=high
AZURE_OPENAI_TIMEOUT_SECONDS=600
MOCK_AI_SERVICES=false
```

Leaving `AZURE_OPENAI_API_KEY` empty enables Entra workload authentication. For a
short local test, an Azure OpenAI key can be placed in `.env`; never commit it.

The image deployment must support the edit endpoint because every follow-up chat
instruction sends the current PNG as the reference for the next version.

## 4. Microsoft Graph mail

The workload application needs Microsoft Graph **Application** permission
`Mail.Send`, with tenant admin consent. Configure an Exchange application access
policy or equivalent application RBAC scope so it can send only through the
intended mailbox.

The mailbox must already exist as a user or shared mailbox:

```dotenv
GRAPH_SENDER_MAILBOX=securityawareness@your-company.com
MOCK_EMAIL_SERVICE=false
```

The app sends to the addresses entered in each campaign. It embeds the current
PNG inline in the HTML body and also identifies it as the poster attachment.

## 5. Azure Database for PostgreSQL (optional)

For password authentication:

```dotenv
DATABASE_URL=postgresql+psycopg://user:password@server.postgres.database.azure.com:5432/database?sslmode=require
DATABASE_AUTH_MODE=password
```

For Entra authentication, create/map the workload principal as a database user
and grant only the required table/schema privileges:

```dotenv
DATABASE_URL=postgresql+psycopg://workload-principal@server.postgres.database.azure.com:5432/database?sslmode=require
DATABASE_AUTH_MODE=entra
AZURE_DATABASE_SCOPE=https://ossrdbms-aad.database.windows.net/.default
```

The starter performs additive table creation and small compatibility migrations
at startup. Use a dedicated migration system such as Alembic before a larger
production rollout.

## 6. Network access

If the Azure OpenAI or PostgreSQL resources use selected networks, the computer,
container host, App Service, VM, or subnet running this application must have an
allowed path. A browser user's IP does not become the backend's outbound IP.

For local Docker testing, allow the workstation/network's current public egress
IP. For Azure production, prefer private endpoints and VNet integration or allow
the stable outbound addresses of the hosting service.

## 7. Start and verify

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose logs -f app
```

Open <http://localhost:8000>, sign in, and create a campaign. Verify that:

- `created_by` contains the signed-in employee.
- the campaign displays **Waiting to generate** while poster version 1 is built.
- a follow-up prompt creates version 2.
- the studio exposes only the Azure OpenAI revision chat.
- revising clears approval.
- sending uses the configured shared mailbox.

Do not put secrets, API keys, recipient lists, or generated production data in
source control.
