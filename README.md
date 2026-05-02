# 📱 WhatsApp → Google Sheets Bot

A WhatsApp bot (via Twilio) that lets you view, add, and update rows in your Google Sheet — all from a chat.

---

## 🗂️ Files

| File | Purpose |
|------|---------|
| `app.py` | Flask webhook — handles WhatsApp messages & conversation flow |
| `sheets.py` | Google Sheets API — read, append, update |
| `requirements.txt` | Python dependencies |
| `render.yaml` | One-click deploy config for Render.com |

---

## ⚙️ Setup Guide

### Step 1 — Google Sheets API Credentials

You said you already have Google Cloud set up ✅. Just make sure:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **Google Sheets API** for your project
3. Create a **Service Account** → download the JSON key
4. Open your Google Sheet → click **Share** → share it with the service account email (e.g. `bot@your-project.iam.gserviceaccount.com`) with **Editor** access
5. Rename the JSON file to `credentials.json` (for local testing) OR paste its contents as `GOOGLE_CREDENTIALS_JSON` env variable on Render

---

### Step 2 — Twilio Sandbox Setup

1. Go to [twilio.com/console](https://console.twilio.com/)
2. Navigate to **Messaging → Try it out → Send a WhatsApp message**
3. Follow the instructions to join the sandbox (send a code via WhatsApp)
4. Note your **Account SID** and **Auth Token** (not needed in the bot code itself, but useful for reference)

---

### Step 3 — Deploy to Render (Free)

1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com/) → New → Web Service → connect your repo
3. It auto-detects `render.yaml` — just fill in:
   - `GOOGLE_CREDENTIALS_JSON` → paste the full contents of your credentials JSON
4. Click **Deploy** — you'll get a public URL like `https://whatsapp-sheet-bot.onrender.com`

---

### Step 4 — Connect Twilio Webhook

1. In Twilio Console → WhatsApp Sandbox Settings
2. Set **"When a message comes in"** to:
   ```
   https://your-app.onrender.com/webhook
   ```
3. Method: `HTTP POST`
4. Save

---

### Step 5 — Test It!

Send any of these from WhatsApp to your Twilio sandbox number:

| Message | What happens |
|---------|-------------|
| `hi` | Welcome + help menu |
| `show` | Lists all tasks from the sheet |
| `add` | Starts guided flow to add a new task |
| `update` | Shows task list → pick one → edit Status/Priority/Owner |
| `help` | Shows command menu |

---

## 🧠 Conversation Flow

```
You: show
Bot: 📊 Current Tasks: ...

You: update
Bot: Which task? 1. Identify trending SKUs ...

You: 3
Bot: Editing: Keyword research. Which field? 1.Status 2.Priority 3.Owner

You: 1
Bot: What should the new Status be?

You: Done
Bot: ✅ Updated! Task: Keyword research | Status: Done
```

---

## 🔧 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Put your credentials.json in the project folder

# Run locally
python app.py

# In another terminal, expose it with ngrok
ngrok http 5000

# Paste the ngrok URL into Twilio sandbox webhook
```

---

## 📋 Sheet Structure Expected

The bot reads **Sheet tab named "Master Tasks"** with these columns:

| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| Category | Task | Status | Priority | Owner | Frequency | KPI/Goal |

> ⚠️ Make sure your sheet tab is named **"Master Tasks"** or update `SHEET_NAME` in `render.yaml`

---

## 🚀 Next Steps (Optional Upgrades)

- Add support for updating the **Weekly Tracker** tab (checkboxes by day)
- Add a `search <keyword>` command to filter tasks
- Add reminder notifications via Twilio outbound messages
