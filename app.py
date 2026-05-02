from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from sheets import (get_all_rows, append_row, update_cell,
                    get_weekly_rows, update_weekly_cell)
from apscheduler.schedulers.background import BackgroundScheduler
import os, pytz

app = Flask(__name__)
sessions = {}

# ── Twilio outbound config ────────────────────────────────────────────────────
TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM  = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

REMINDER_NUMBERS = [
    "whatsapp:+918700727226",
    "whatsapp:+919971517367",
]

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

S_ICON = {"pending": "🔴", "in progress": "🟡", "done": "🟢", "ongoing": "🔵"}
P_ICON = {"high": "🔺", "medium": "🔸", "low": "🔹"}

HELP_TEXT = """👋 *Welcome to your Sheet Bot!*
_Your Amazon task tracker, right here on WhatsApp._

━━━━━━━━━━━━━━━━━━
📋 *COMMANDS*
━━━━━━━━━━━━━━━━━━

📊 *list*  _or_  *list 2*
   View all tasks, 10 per page

🔍 *search <keyword>*
   Filter tasks by any word
   _e.g. search inventory_

➕ *add*
   Add a new task to the sheet
   _Guided 7-step flow_

✏️ *update*
   Change status, priority or owner
   _Paginated task picker_

📅 *weekly*
   Tick off tasks day by day

🚫 *cancel*
   Cancel whatever you're doing

❓ *help*
   Show this menu again

━━━━━━━━━━━━━━━━━━
⏰ *REMINDERS*
━━━━━━━━━━━━━━━━━━
Every morning at *9:00 AM IST* you'll
get a summary of all pending tasks.

━━━━━━━━━━━━━━━━━━
💡 *QUICK REFERENCE*
━━━━━━━━━━━━━━━━━━
*Status:* Pending | In Progress | Done
*Priority:* High | Medium | Low
*Owner:* Abdullah | Haris"""


# ── Session helpers ───────────────────────────────────────────────────────────
def get_session(phone):
    if phone not in sessions:
        sessions[phone] = {"state": "idle", "data": {}}
    return sessions[phone]

def reset_session(phone):
    sessions[phone] = {"state": "idle", "data": {}}


# ── Outbound reminder ─────────────────────────────────────────────────────────
def send_reminder(body):
    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        for number in REMINDER_NUMBERS:
            client.messages.create(from_=TWILIO_FROM, to=number, body=body)
        print(f"[reminder] Sent to {len(REMINDER_NUMBERS)} numbers")
    except Exception as e:
        print(f"[reminder] Error: {e}")


def daily_summary():
    rows = get_all_rows()
    if not rows:
        return
    pending = [r for r in rows[1:] if len(r) > 2 and r[2].lower() in ("pending", "in progress", "ongoing")]
    if not pending:
        send_reminder("☀️ *Good Morning!*\n━━━━━━━━━━━━━━━━━━\n🎉 All tasks are done. Great work today!")
        return
    lines = ["☀️ *Good Morning!*\n━━━━━━━━━━━━━━━━━━\n📋 *Tasks needing attention:*\n"]
    for i, r in enumerate(pending[:15], 1):
        task     = r[1] if len(r) > 1 else "?"
        status   = r[2] if len(r) > 2 else "?"
        priority = r[3] if len(r) > 3 else "?"
        lines.append(f"{i}. *{task}*\n   {S_ICON.get(status.lower(),'⚪')} {status}  {P_ICON.get(priority.lower(),'')} {priority}")
    if len(pending) > 15:
        lines.append(f"\n_...and {len(pending) - 15} more. Send *list* to see all._")
    send_reminder("\n".join(lines))


# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
scheduler.add_job(daily_summary, "cron", hour=9, minute=0)
scheduler.start()


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body", "").strip()
    sender       = request.form.get("From", "")
    resp = MessagingResponse()
    msg  = resp.message()
    session = get_session(sender)
    reply = handle_message(incoming_msg, sender, session, session["state"])
    msg.body(reply)
    return str(resp)

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200


# ── Helpers ───────────────────────────────────────────────────────────────────
def paginate_tasks(rows, page, page_size=10):
    data_rows   = rows[1:]
    total       = len(data_rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page        = max(1, min(page, total_pages))
    start       = (page - 1) * page_size
    return data_rows[start:start + page_size], page, total_pages, start


# ── Message handler ───────────────────────────────────────────────────────────
def handle_message(text, sender, session, state):
    cmd = text.lower().strip()

    # ── CANCEL — works from any state ─────────────────────────────────────────
    if cmd == "cancel":
        reset_session(sender)
        return "🚫 *Cancelled.*\n\nSend *help* to see all commands."

    # ── IDLE ──────────────────────────────────────────────────────────────────
    if state == "idle":

        if cmd in ("hi", "hello", "hey", "start", "help"):
            return HELP_TEXT

        # LIST (renamed from show)
        elif cmd == "list" or (len(cmd.split()) == 2 and cmd.split()[0] == "list" and cmd.split()[1].isdigit()):
            rows = get_all_rows()
            if not rows:
                return "📭 No data found in the sheet."
            parts = cmd.split()
            page  = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            slice_, page, total_pages, start = paginate_tasks(rows, page)
            lines = [f"📊 *TASKS — Page {page} of {total_pages}*\n━━━━━━━━━━━━━━━━━━"]
            for i, row in enumerate(slice_, start=start + 1):
                task     = row[1] if len(row) > 1 else "?"
                status   = row[2] if len(row) > 2 else "?"
                priority = row[3] if len(row) > 3 else "?"
                lines.append(f"{i}. *{task}*\n   {S_ICON.get(status.lower(),'⚪')} {status}  {P_ICON.get(priority.lower(),'')} {priority}")
            if page < total_pages:
                lines.append(f"\n➡️ Send *list {page + 1}* for next page.")
            lines.append("\n━━━━━━━━━━━━━━━━━━\n💬 *add* | *update* | *weekly* | *search <keyword>*")
            return "\n".join(lines)

        # SEARCH
        elif cmd.startswith("search "):
            keyword = text[7:].strip().lower()
            if not keyword:
                return "🔍 Provide a keyword. _e.g. search inventory_"
            rows = get_all_rows()
            if not rows:
                return "📭 No data found in the sheet."
            matches = [r for r in rows[1:] if any(keyword in str(c).lower() for c in r)]
            if not matches:
                return f"🔍 No tasks found matching *'{keyword}'*."
            lines = [f"🔍 *Results for '{keyword}'*\n━━━━━━━━━━━━━━━━━━"]
            for r in matches[:15]:
                cat      = r[0] if len(r) > 0 else "?"
                task     = r[1] if len(r) > 1 else "?"
                status   = r[2] if len(r) > 2 else "?"
                priority = r[3] if len(r) > 3 else "?"
                lines.append(f"• *{task}*\n  _📁 {cat}_  {S_ICON.get(status.lower(),'⚪')} {status} | {priority}")
            if len(matches) > 15:
                lines.append(f"\n_...and {len(matches)-15} more. Try a specific keyword._")
            return "\n".join(lines)

        # ADD
        elif cmd == "add":
            session["state"] = "add_category"
            return ("➕ *Add New Task*\n━━━━━━━━━━━━━━━━━━\n\n"
                    "*Step 1 of 7* — What *category* is this task?\n\n"
                    "📁 e.g. Inventory, Pricing, Advertising, Reviews\n\n"
                    "_Send *cancel* anytime to stop._")

        # UPDATE (paginated)
        elif cmd == "update" or (len(cmd.split()) == 2 and cmd.split()[0] == "update" and cmd.split()[1].isdigit()):
            rows = get_all_rows()
            if not rows:
                return "📭 The sheet is empty."
            parts = cmd.split()
            page  = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            slice_, page, total_pages, start = paginate_tasks(rows, page)
            lines = [f"✏️ *UPDATE A TASK — Page {page} of {total_pages}*\n━━━━━━━━━━━━━━━━━━\nReply with the task number:\n"]
            for i, row in enumerate(slice_, start=start + 1):
                task   = row[1] if len(row) > 1 else "?"
                status = row[2] if len(row) > 2 else "?"
                lines.append(f"{i}. {task} {S_ICON.get(status.lower(),'')}")
            if page < total_pages:
                lines.append(f"\n➡️ Send *update {page + 1}* to see more tasks.")
            session["state"] = "update_pick_row"
            session["data"]["rows"] = rows
            return "\n".join(lines)

        # WEEKLY
        elif cmd == "weekly" or (len(cmd.split()) == 2 and cmd.split()[0] == "weekly" and cmd.split()[1].isdigit()):
            rows = get_weekly_rows()
            if not rows:
                return "📭 The Weekly Tracker is empty."
            parts = cmd.split()
            page  = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            slice_, page, total_pages, start = paginate_tasks(rows, page)
            lines = [f"📅 *WEEKLY TRACKER — Page {page} of {total_pages}*\n━━━━━━━━━━━━━━━━━━\nPick a task:\n"]
            for i, row in enumerate(slice_, start=start + 1):
                task = row[1] if len(row) > 1 else "?"
                lines.append(f"{i}. {task}")
            if page < total_pages:
                lines.append(f"\n➡️ Send *weekly {page + 1}* to see more.")
            session["state"] = "weekly_pick_row"
            session["data"]["weekly_rows"] = rows
            return "\n".join(lines)

        else:
            return "🤖 I didn't understand that.\n\nSend *help* to see all commands."

    # ── ADD flow ──────────────────────────────────────────────────────────────
    elif state == "add_category":
        session["data"]["category"] = text
        session["state"] = "add_task"
        return "✅ Got it!\n\n*Step 2 of 7* — What is the *task name*?"

    elif state == "add_task":
        session["data"]["task"] = text
        session["state"] = "add_status"
        return ("✅ Got it!\n\n*Step 3 of 7* — What is the *status*?\n\n"
                "🔴 *Pending*\n"
                "🟡 *In Progress*\n"
                "🟢 *Done*")

    elif state == "add_status":
        session["data"]["status"] = text
        session["state"] = "add_priority"
        return ("✅ Got it!\n\n*Step 4 of 7* — What is the *priority*?\n\n"
                "🔺 *High*\n"
                "🔸 *Medium*\n"
                "🔹 *Low*")

    elif state == "add_priority":
        session["data"]["priority"] = text
        session["state"] = "add_owner"
        return ("✅ Got it!\n\n*Step 5 of 7* — Who is the *owner*?\n\n"
                "👤 *Abdullah*\n"
                "👤 *Haris*")

    elif state == "add_owner":
        session["data"]["owner"] = text
        session["state"] = "add_frequency"
        return ("✅ Got it!\n\n*Step 6 of 7* — What is the *frequency*?\n\n"
                "📆 *Daily*\n"
                "📅 *Weekly*\n"
                "🗓️ *Monthly*\n"
                "⚡ *One-time*")

    elif state == "add_frequency":
        session["data"]["frequency"] = text
        session["state"] = "add_kpi"
        return "✅ Got it!\n\n*Step 7 of 7* — What is the *KPI / Goal* for this task?\n\n_e.g. 2-3 winning products/week, ROAS > 2.5_"

    elif state == "add_kpi":
        session["data"]["kpi"] = text
        d = session["data"]
        new_row = [
            d.get("category", ""),
            d.get("task", ""),
            d.get("status", "Pending"),
            d.get("priority", "Medium"),
            d.get("owner", ""),
            d.get("frequency", ""),
            d.get("kpi", ""),
        ]
        success = append_row(new_row)
        reset_session(sender)
        if success:
            return (f"🎉 *Task Added!*\n━━━━━━━━━━━━━━━━━━\n"
                    f"📁 *Category:* {new_row[0]}\n"
                    f"📝 *Task:* {new_row[1]}\n"
                    f"🔄 *Status:* {new_row[2]}\n"
                    f"⚡ *Priority:* {new_row[3]}\n"
                    f"👤 *Owner:* {new_row[4]}\n"
                    f"📆 *Frequency:* {new_row[5]}\n"
                    f"🎯 *KPI/Goal:* {new_row[6]}")
        return "❌ Failed to add task. Please try again."

    # ── UPDATE flow ───────────────────────────────────────────────────────────
    elif state == "update_pick_row":
        rows = session["data"].get("rows", [])
        try:
            row_num = int(text)
            chosen  = rows[row_num]
            session["data"]["row_index"]  = row_num
            session["data"]["chosen_row"] = chosen
            session["state"] = "update_pick_field"
            task_name = chosen[1] if len(chosen) > 1 else "?"
            status    = chosen[2] if len(chosen) > 2 else "?"
            priority  = chosen[3] if len(chosen) > 3 else "?"
            owner     = chosen[4] if len(chosen) > 4 else "?"
            return (f"✏️ *Editing:* _{task_name}_\n━━━━━━━━━━━━━━━━━━\n"
                    f"Current: {S_ICON.get(status.lower(),'⚪')} {status} | {P_ICON.get(priority.lower(),'')} {priority} | 👤 {owner}\n\n"
                    "Which field to update?\n\n"
                    "1️⃣ Status\n2️⃣ Priority\n3️⃣ Owner\n\n"
                    "Reply with *1*, *2*, or *3*")
        except (ValueError, IndexError):
            reset_session(sender)
            return "❌ Invalid number. Send *update* to try again."

    elif state == "update_pick_field":
        field_map = {"1": (2, "Status"), "2": (3, "Priority"), "3": (4, "Owner")}
        if text not in field_map:
            return "⚠️ Please reply with *1*, *2*, or *3*."
        col_index, field_name = field_map[text]
        session["data"]["col_index"]  = col_index
        session["data"]["field_name"] = field_name
        session["state"] = "update_enter_value"
        if field_name == "Status":
            return "💬 New *Status*?\n\n🔴 Pending\n🟡 In Progress\n🟢 Done"
        elif field_name == "Priority":
            return "💬 New *Priority*?\n\n🔺 High\n🔸 Medium\n🔹 Low"
        else:
            return "💬 New *Owner*?\n\n👤 Abdullah\n👤 Haris"

    elif state == "update_enter_value":
        row_index  = session["data"]["row_index"]
        col_index  = session["data"]["col_index"]
        field_name = session["data"]["field_name"]
        task_name  = session["data"]["chosen_row"][1] if len(session["data"]["chosen_row"]) > 1 else "?"
        success = update_cell(row_index + 1, col_index + 1, text)
        reset_session(sender)
        if success:
            return f"✅ *Updated!*\n━━━━━━━━━━━━━━━━━━\n📝 *Task:* {task_name}\n🔧 *{field_name}:* {text}"
        return "❌ Update failed. Please try again."

    # ── WEEKLY TRACKER flow ───────────────────────────────────────────────────
    elif state == "weekly_pick_row":
        rows = session["data"].get("weekly_rows", [])
        try:
            row_num = int(text)
            chosen  = rows[row_num]
            session["data"]["weekly_row_index"] = row_num
            session["data"]["weekly_chosen"]    = chosen
            session["state"] = "weekly_pick_day"
            task_name = chosen[1] if len(chosen) > 1 else "?"
            day_lines = []
            for i, day in enumerate(DAYS):
                val  = chosen[i + 2] if len(chosen) > i + 2 else "FALSE"
                tick = "✅ Done" if str(val).upper() == "TRUE" else "○ Pending"
                day_lines.append(f"{i+1}. *{day}* — {tick}")
            return (f"📅 *{task_name}*\n━━━━━━━━━━━━━━━━━━\n" +
                    "\n".join(day_lines) +
                    "\n\nReply with day number *(1=Mon ... 7=Sun)*")
        except (ValueError, IndexError):
            reset_session(sender)
            return "❌ Invalid number. Send *weekly* to try again."

    elif state == "weekly_pick_day":
        try:
            day_num = int(text)
            if day_num < 1 or day_num > 7:
                return "⚠️ Please reply with a number between *1* and *7*."
            session["data"]["weekly_day_index"] = day_num - 1
            day_name = DAYS[day_num - 1]
            session["state"] = "weekly_pick_value"
            return f"Mark *{day_name}* as:\n\n1️⃣ Done ✅\n2️⃣ Not done ○"
        except ValueError:
            return "⚠️ Please reply with a number between *1* and *7*."

    elif state == "weekly_pick_value":
        if text not in ("1", "2"):
            return "⚠️ Reply *1* for Done or *2* for Not done."
        value     = "TRUE" if text == "1" else "FALSE"
        row_index = session["data"]["weekly_row_index"]
        day_index = session["data"]["weekly_day_index"]
        task_name = session["data"]["weekly_chosen"][1] if len(session["data"]["weekly_chosen"]) > 1 else "?"
        day_name  = DAYS[day_index]
        col       = day_index + 3
        success   = update_weekly_cell(row_index + 1, col, value)
        reset_session(sender)
        if success:
            tick = "✅ Done" if value == "TRUE" else "○ Not done"
            return f"✅ *Updated!*\n━━━━━━━━━━━━━━━━━━\n📝 *Task:* {task_name}\n📅 *{day_name}:* {tick}"
        return "❌ Update failed. Please try again."

    # Fallback
    reset_session(sender)
    return "⚠️ Something went wrong. Send *help* to start over."


if __name__ == "__main__":
    app.run(debug=True, port=5000)
