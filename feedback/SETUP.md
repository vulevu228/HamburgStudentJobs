# Feedback form backend: Azure setup (personal Pay-As-You-Go subscription)

The site's "Feedback" form and the "Report" button on each job post to a small Azure Function.
It stores every message in **Azure Table Storage in Frankfurt**, in your own storage account.
Nothing is published and only you can read it. Cost: a few cents a month.

Run every command in **your own PowerShell terminal**, one line each. Your PC is already signed in
to the personal account (`az account show` shows "Azure subscription 1").

Names used below: resource group `rg-hsjfeedback`, storage account `hsjfeedbackemir`,
Function App `hsj-feedback-emir`. If a name is taken, change it everywhere
(storage: 3-24 lowercase letters/digits).

## 1. Resource group and storage account (the messages live here)
```powershell
az group create --name rg-hsjfeedback --location germanywestcentral
```
```powershell
az storage account create --name hsjfeedbackemir --resource-group rg-hsjfeedback --location germanywestcentral --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false
```

## 2. The Function App
```powershell
az functionapp create --name hsj-feedback-emir --resource-group rg-hsjfeedback --storage-account hsjfeedbackemir --consumption-plan-location germanywestcentral --os-type Linux --runtime python --runtime-version 3.11 --functions-version 4
```

## 3. Settings
A secret "salt" for the spam limit (a random value made on your PC; it never appears on screen):
```powershell
$b = New-Object byte[] 32; [System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($b); $salt = [Convert]::ToBase64String($b); az functionapp config appsettings set --name hsj-feedback-emir --resource-group rg-hsjfeedback --settings "RATE_SALT=$salt" "ALLOWED_ORIGINS=https://hamburgstudentjobs.de" --output none; Remove-Variable salt, b
```
Only your site may send to the function (browser rule, CORS):
```powershell
az functionapp cors add --name hsj-feedback-emir --resource-group rg-hsjfeedback --allowed-origins https://hamburgstudentjobs.de
```

Email me a copy of every new message. This reuses the email service you already built for AI News Watch
(`ainews-acs` in `rg-ainews`), so nothing new is created. The key goes straight from Azure into the app and
never shows on screen:
```powershell
$sender = "DoNotReply@" + (az communication email domain show --domain-name AzureManagedDomain --email-service-name ainews-email --resource-group rg-ainews --query fromSenderDomain -o tsv); $acs = az communication list-key --name ainews-acs --resource-group rg-ainews --query primaryConnectionString -o tsv; az functionapp config appsettings set --name hsj-feedback-emir --resource-group rg-hsjfeedback --settings "ACS_CONNECTION_STRING=$acs" "ACS_SENDER=$sender" "NOTIFY_TO=emiravni@proton.me" --output none; Remove-Variable acs
```
The emails come from the same `DoNotReply@...azurecomm.net` address as the AI News alerts, so in Proton they
also land under **Newsletters**. When the visitor left an email address, just press Reply: the answer goes
to them, not to the DoNotReply address. At most 40 emails a day are sent; every message is saved either way.

## 4. Upload the code
```powershell
cd C:\Users\emira\Projects\GitHub-Projects\HamburgStudentJobs\feedback
```
```powershell
func azure functionapp publish hsj-feedback-emir --python
```
The end of the output must list **Submit** and **Purge**. If the list is empty, run this once and
check again with the second command:
```powershell
az resource invoke-action --action syncfunctiontriggers --resource-type Microsoft.Web/sites --name hsj-feedback-emir -g rg-hsjfeedback
```
```powershell
az functionapp function list --name hsj-feedback-emir --resource-group rg-hsjfeedback --query "[].name" -o tsv
```

## 5. Your form address (send it to Claude)
```powershell
"https://" + (az functionapp show --name hsj-feedback-emir --resource-group rg-hsjfeedback --query defaultHostName -o tsv) + "/api/feedback"
```
Claude puts this address into `docs/app.js` (`FEEDBACK_URL`). Until then the form stays hidden on the live site.

## 6. Test it
Send one test message (the address from step 5 goes after `-Uri`):
```powershell
Invoke-RestMethod -Method Post -Uri PASTE_ADDRESS_HERE -Headers @{Origin="https://hamburgstudentjobs.de"} -ContentType "application/json" -Body '{"kind":"other","message":"Test from SETUP step 6","elapsed_ms":5000}'
```
It should answer `ok : True`.

## Reading your messages
**Portal:** Storage accounts -> `hsjfeedbackemir` -> **Storage browser** -> **Tables** -> `feedback`.
Newest messages are at the top. You can edit the `status` column (for example to `done`) or delete a row
once you have dealt with it.

**Terminal:**
```powershell
az storage entity query --account-name hsjfeedbackemir --table-name feedback --auth-mode key --select received kind message email job_title status -o table
```

Each row has: `received` (UTC time), `kind` (question / idea / criticism / bug / job / employer / other),
`message`, `email` (only if they gave one), `job_id` + `job_title` (for "Report" on a job), `lang`, `page`, `status`.

## What it does on its own
- **Spam protection:** only accepts posts from hamburgstudentjobs.de; ignores bots (hidden trap field, forms sent
  in under 3 seconds); at most 5 messages per visitor per day. No IP address is stored, only a salted
  one-way hash that is deleted the next day.
- **Purge** runs daily at 03:15 UTC: deletes yesterday's spam-limit hashes and messages older than 12 months
  (the privacy page promises this).
- **Email copy** of each new message to NOTIFY_TO (step 3), at most 40 a day. If sending fails, the message
  is still saved and the visitor still sees "thank you"; the error shows up in Application Insights.
- Nothing is ever shown on the site. The table is private to your storage account.

## An email when the function fails
Portal -> `hsj-feedback-emir` -> **Application Insights** -> **Alerts** -> **Create** -> **Alert rule**:
- **Condition:** signal **Failed requests** (a *metric*, not a log search - metric alerts cost cents a month),
  aggregation **Count**, operator **Greater than**, threshold **0**.
- **Check every 1 hour, lookback period 1 hour.** Keep them equal: with a longer lookback the same failure
  stays in the window for several checks and you get several emails for it.
- **Actions:** an action group that emails emiravni@proton.me (you can reuse the one from AI News Watch).
- **Details:** severity 2 (Warning), name `hsj-feedback-failed`; leave "Automatically resolve alerts" on.
- Check the monthly cost estimate shown on the last page before you press Create.

Note: the function answers refused visitors (too many messages, wrong site, bad input) with normal "no"
answers (codes 400/403/429), not crashes. Whether Application Insights counts those as "failed" is not
verified yet: after your step-6 test, send one test with a wrong Origin and look at Application Insights ->
Failures. If it shows up there, tell Claude - the alert should then filter on result code 5xx only.

## Local testing (no Azure needed)
```powershell
cd C:\Users\emira\Projects\GitHub-Projects\HamburgStudentJobs\feedback
py -3.11 test_local.py
```
Full local run: `func start --port 7079` (uses `local.settings.json` with `FEEDBACK_STORE=memory`), then open
the site on `http://localhost:8791` - the form posts to the local function automatically.

---

# Daily job alerts by email (added 30 Sep 2026)

Visitors can click **"Email me new jobs like these"** above the results. They get a confirmation email
(double opt-in, required in Germany) and, once confirmed, one email each morning with the day's new jobs that
match the filters they had set. Unsubscribe = one click in every email (also the mail program's own button).

The code is in this folder: `Alerts` (sign-up / confirm / unsubscribe, `POST /api/alerts/...`), `Digest`
(timer, every 20 min 05:00-09:40 UTC: waits until the day's data is published, then sends) and `Purge`
(now also deletes sign-ups that were never confirmed, after 7 days). Subscribers live in a new table `alerts`
in the same storage account (`hsjfeedbackemir`).

**Why a separate email sender:** the feedback copies use Azure's free `DoNotReply@...azurecomm.net` address.
That address may only send about 10 emails an hour and lands in spam/Newsletters, so it can't carry the
alerts. The alerts send from **alerts@hamburgstudentjobs.de**, which needs your domain verified with Azure (DNS records at INWX).

Do the steps in order. **Tell Claude when step 6 works: only then the site change goes live.** Until then the live
site has no alert button, so nothing is half-working in public.

## 1. Email service + your domain (Germany data location)
```powershell
az communication email create --name hsj-email --resource-group rg-hsjfeedback --location global --data-location Germany
```
```powershell
az communication email domain create --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --location global --domain-management CustomerManaged --user-engmnt-tracking Disabled
```
(If `Germany` is refused as data location, use `Europe` in step 1 **and** step 4, and tell Claude: the privacy page says Germany.)

## 2. DNS records at INWX
Show the records Azure wants:
```powershell
az communication email domain show --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --query verificationRecords -o json
```
You get 4 records: **Domain** (TXT), **SPF** (TXT), **DKIM** (CNAME), **DKIM2** (CNAME). Add each one at INWX ->
Nameserver -> hamburgstudentjobs.de -> **Add record** (don't touch the existing A / AAAA / CNAME www / GitHub TXT records):
- **Domain** and **SPF**: type TXT, name = empty (the domain itself), value = the `value` shown. Two separate TXT records.
- **DKIM** and **DKIM2**: type CNAME, name = the `name` shown **without** `.hamburgstudentjobs.de` at the end
  (e.g. `selector1-azurecomm-prod-net._domainkey`), value = the `value` shown.
- Also add one DMARC record (big mail providers expect it): type TXT, name `_dmarc`, value `v=DMARC1; p=none;`

Wait ~15 minutes, then start the checks (one line each):
```powershell
foreach ($t in "Domain","SPF","DKIM","DKIM2") { az communication email domain initiate-verification --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --verification-type $t --output none }
```
Check after a few minutes; all four must say **Verified**:
```powershell
az communication email domain show --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --query "verificationStates" -o table
```
(Portal alternative: Email Communication Services -> `hsj-email` -> Provision domains -> hamburgstudentjobs.de -> Configure.)

## 3. The sender name alerts@hamburgstudentjobs.de
```powershell
az communication email domain sender-username create --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --sender-username alerts --username alerts --display-name "Hamburg Student Jobs"
```

## 4. The sending resource, linked to the domain
```powershell
az communication create --name hsj-acs --resource-group rg-hsjfeedback --location global --data-location Germany
```
```powershell
$dom = az communication email domain show --domain-name hamburgstudentjobs.de --email-service-name hsj-email --resource-group rg-hsjfeedback --query id -o tsv; az communication update --name hsj-acs --resource-group rg-hsjfeedback --linked-domains $dom --output none
```

## 5. Settings + upload the code
The key goes from Azure straight into the app, never on screen:
```powershell
$acs = az communication list-key --name hsj-acs --resource-group rg-hsjfeedback --query primaryConnectionString -o tsv; az functionapp config appsettings set --name hsj-feedback-emir --resource-group rg-hsjfeedback --settings "ALERT_ACS_CONNECTION_STRING=$acs" "ALERT_SENDER=alerts@hamburgstudentjobs.de" "ALERT_API_URL=https://hsj-feedback-emir.azurewebsites.net/api/alerts" --output none; Remove-Variable acs
```
```powershell
cd C:\Users\emira\Projects\GitHub-Projects\HamburgStudentJobs\feedback
```
```powershell
func azure functionapp publish hsj-feedback-emir --python
```
The list at the end must now show **Alerts, Digest, Purge, Submit** (if not: the `syncfunctiontriggers` command from the feedback setup, step 4).

## 6. Test with your own address
```powershell
Invoke-RestMethod -Method Post -Uri https://hsj-feedback-emir.azurewebsites.net/api/alerts/subscribe -Headers @{Origin="https://hamburgstudentjobs.de"} -ContentType "application/json" -Body '{"email":"emiravni@proton.me","filters":"type=Werkstudent","lang":"en","elapsed_ms":5000}'
```
It answers `ok : True` and a confirmation email from **alerts@hamburgstudentjobs.de** arrives. Check it's in the inbox,
not spam. **Don't click the link yet:** the site part isn't live until Claude pushes it. Tell Claude, then click it.

## Reading / managing subscribers
Portal: Storage accounts -> `hsjfeedbackemir` -> Storage browser -> Tables -> `alerts`
(`status` pending/active, `filters`, `lang`, `confirmed` = proof of consent, `last_sent`, `sent_count`).
Deleting a row = unsubscribing that person. Digest runs show up in Application Insights as `digest: {...sent...}`.

## Limits
- One email per subscriber per day at most. No email on days without a matching new job.
- Each run sends at most 25 digests (`DIGEST_MAX_PER_RUN`), 3 runs an hour, so about 75 an hour: under Azure's default
  limit for a custom domain. With a few hundred subscribers, ask Azure for a higher sending quota (Portal support
  request) and raise `DIGEST_MAX_PER_RUN`.
- If the day's data isn't published by 09:40 UTC, no alerts go out that day.
- Cost: Azure email is about $0.00025 per email, so 1,000 alerts = 25 cents.
