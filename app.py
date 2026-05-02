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

# Numbers that receive daily reminders
REMINDER_NUMBERS = [
    "whatsapp:+918700727226",
    "whatsapp:+919971517367",
]

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

HELP_TEXT = """WhatsApp Sheet Bot

Commands:
- show / show 2       View tasks (paginated)
- search <keyword>    Filter tasks by keyword
- add                 Add a new task
- update              Update a task field
- weekly              Update Weekly Tracker
- help                Show this menu"""


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
    """9 AM IST daily summary of pending/in-progress tasks."""
    rows = get_all_rows()
    if not rows:
        return
    pending = [r for r in rows[1:] if len(r) > 2 and r[2].lower() in ("pending", "in progress", "ongoing")]
    if not pending:
        send_reminder("Good morning! All tasks are marked done. Great work!")
        return
    lines = ["Good morning! Tasks needing attention today:\n"]
    for i, r in enumerate(pending[:15], 1):
        task     = r[1] if len(r) > 1 else "?"
        status   = r[2] if len(r) > 2 else "?"
        priority = r[3] if len(r) > 3 else "?"
        lines.append(f"{i}. {task} [{priority}] - {status}")
    if len(pending) > 15:
        lines.append(f"...and {len(pending) - 15} more. Send 'show' to see all.")
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


# ── Message handler ───────────────────────────────────────────────────────────
def handle_message(text, sender, session, state):
    cmd = text.lower().strip()

    # ── IDLE ──────────────────────────────────────────────────────────────────
    if state == "idle":

        if cmd in ("hi", "hello", "hey", "start", "help"):
            return HELP_TEXT

        elif cmd == "show" or (len(cmd.split()) == 2 and cmd.split()[0] == "show" and cmd.split()[1].isdigit()):
            rows = get_all_rows()
            if not rows:
                return "No data found in the sheet."
            data_rows = rows[1:]
            parts     = cmd.split()
            page      = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            page_size = 10
            total     = len(data_rows)
            total_pages = (total + page_size - 1) // page_size
            page  = max(1, min(page, total_pages))
            start = (page - 1) * page_size
            lines = [f"Tasks (Page {page}/{total_pages}):\n"]
            for i, row in enumerate(data_rows[start:start + page_size], start=start + 1):
                task     = row[1] if len(row) > 1 else "?"
                status   = row[2] if len(row) > 2 else "?"
                priority = row[3] if len(row) > 3 else "?"
                lines.append(f"{i}. {task} - {status} | {priority}")
            if page < total_pages:
                lines.append(f"\nSend 'show {page + 1}' for next page.")
            lines.append("\nSend 'add', 'update', 'weekly', or 'search <keyword>'.")
            return "\n".join(lines)

        elif cmd.startswith("search "):
            keyword = text[7:].strip().lower()
            if not keyword:
                return "Provide a keyword. E.g. 'search inventory'"
            rows = get_all_rows()
            if not rows:
                return "No data found in the sheet."
            matches = [r for r in rows[1:] if any(keyword in str(cell).lower() for cell in r)]
            if not matches:
                return f"No tasks found matching '{keyword}'."
            lines = [f"Results for '{keyword}':\n"]
            for r in matches[:15]:
                cat      = r[0] if len(r) > 0 else "?"
                task     = r[1] if len(r) > 1 else "?"
                status   = r[2] if len(r) > 2 else "?"
                priority = r[3] if len(r) > 3 else "?"
                lines.append(f"- [{cat}] {task}\n  {status} | {priority}")
            if len(matches) > 15:
                lines.append(f"\n...and {len(matches) - 15} more results.")
            return "\n".join(lines)

        elif cmd == "add":
            session["state"] = "add_category"
            return "Add New Task\n\nStep 1/5 - Category?\n(e.g. Inventory, Pricing, Advertising)"

        elif cmd == "update":
            rows = get_all_rows()
            if not rows:
                return "Sheet is empty."
            lines = ["Which task to update? Reply with number:\n"]
            for i, row in enumerate(rows[1:21], start=1):
                task = row[1] if len(row) > 1 else "?"
                lines.append(f"{i}. {task}")
            if len(rows) > 21:
                lines.append("\nShowing first 20. Use 'search' to find others.")
            session["state"] = "update_pick_row"
            session["data"]["rows"] = rows
            return "\n".join(lines)

        elif cmd == "weekly":
            rows = get_weekly_rows()
            if not rows:
                return "Weekly Tracker is empty."
            lines = ["Weekly Tracker - Pick a task:\n"]
            for i, row in enumerate(rows[1:21], start=1):
                task = row[1] if len(row) > 1 else "?"
                lines.append(f"{i}. {task}")
            session["state"] = "weekly_pick_row"
            session["data"]["weekly_rows"] = rows
            return "\n".join(lines)

        else:
            return "I didn't understand that. Send 'help' to see commands."

    # ── ADD flow ──────────────────────────────────────────────────────────────
    elif state == "add_category":
        session["data"]["category"] = text
        session["state"] = "add_task"
        return "Step 2/5 - Task name?"

    elif state == "add_task":
        session["data"]["task"] = text
        session["state"] = "add_status"
        return "Step 3/5 - Status?\n(Pending / In Progress / Done / Ongoing)"

    elif state == "add_status":
        session["data"]["status"] = text
        session["state"] = "add_priority"
        return "Step 4/5 - Priority?\n(High / Medium / Low)"

    elif state == "add_priority":
        session["data"]["priority"] = text
        session["state"] = "add_owner"
        return "Step 5/5 - Owner?\n(e.g. You / Marketing / Ops)"

    elif state == "add_owner":
        session["data"]["owner"] = text
        d = session["data"]
        new_row = [d.get("category",""), d.get("task",""), d.get("status","Pending"),
                   d.get("priority","Medium"), d.get("owner",""), "", ""]
        success = append_row(new_row)
        reset_session(sender)
        if success:
            return (f"Task added!\n\nCategory: {new_row[0]}\nTask: {new_row[1]}\n"
                    f"Status: {new_row[2]}\nPriority: {new_row[3]}\nOwner: {new_row[4]}")
        return "Failed to add task. Please try again."

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
            return (f"Editing: {task_name}\n\nWhich field?\n"
                    "1. Status\n2. Priority\n3. Owner\n\nReply with number.")
        except (ValueError, IndexError):
            reset_session(sender)
            return "Invalid number. Send 'update' to try again."

    elif state == "update_pick_field":
        field_map = {"1": (2, "Status"), "2": (3, "Priority"), "3": (4, "Owner")}
        if text not in field_map:
            return "Please reply with 1, 2, or 3."
        col_index, field_name = field_map[text]
        session["data"]["col_index"]  = col_index
        session["data"]["field_name"] = field_name
        session["state"] = "update_enter_value"
        return f"New value for {field_name}?"

    elif state == "update_enter_value":
        row_index  = session["data"]["row_index"]
        col_index  = session["data"]["col_index"]
        field_name = session["data"]["field_name"]
        task_name  = session["data"]["chosen_row"][1] if len(session["data"]["chosen_row"]) > 1 else "?"
        success = update_cell(row_index + 1, col_index + 1, text)
        reset_session(sender)
        if success:
            return f"Updated!\nTask: {task_name}\n{field_name}: {text}"
        return "Update failed. Please try again."

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
                tick = "Done" if str(val).upper() == "TRUE" else "Pending"
                day_lines.append(f"{i+1}. {day} - {tick}")
            return (f"Task: {task_name}\n\nPick a day to toggle:\n" +
                    "\n".join(day_lines) +
                    "\n\nReply with day number (1=Mon ... 7=Sun)")
        except (ValueError, IndexError):
            reset_session(sender)
            return "Invalid number. Send 'weekly' to try again."

    elif state == "weekly_pick_day":
        try:
            day_num = int(text)
            if day_num < 1 or day_num > 7:
                return "Please reply with a number between 1 and 7."
            session["data"]["weekly_day_index"] = day_num - 1
            day_name = DAYS[day_num - 1]
            session["state"] = "weekly_pick_value"
            return f"Mark {day_name} as:\n1. Done\n2. Not done"
        except ValueError:
            return "Please reply with a number between 1 and 7."

    elif state == "weekly_pick_value":
        if text not in ("1", "2"):
            return "Reply 1 for Done or 2 for Not done."
        value     = "TRUE" if text == "1" else "FALSE"
        row_index = session["data"]["weekly_row_index"]
        day_index = session["data"]["weekly_day_index"]
        task_name = session["data"]["weekly_chosen"][1] if len(session["data"]["weekly_chosen"]) > 1 else "?"
        day_name  = DAYS[day_index]
        col = day_index + 3  # A=cat, B=task, C=Mon(col3)...I=Sun(col9)
        success = update_weekly_cell(row_index + 1, col, value)
        reset_session(sender)
        if success:
            tick = "Done" if value == "TRUE" else "Not done"
            return f"Updated!\nTask: {task_name}\n{day_name}: {tick}"
        return "Update failed. Please try again."

    # Fallback
    reset_session(sender)
    return "Something went wrong. Send 'help' to start over."


if __name__ == "__main__":
    app.run(debug=True, port=5000)
