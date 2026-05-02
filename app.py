from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from sheets import get_all_rows, append_row, update_cell, find_row_by_task
import re

app = Flask(__name__)

# In-memory session store (per phone number)
sessions = {}

HELP_TEXT = """👋 *WhatsApp Sheet Bot*

Commands:
• *show* — View all tasks
• *add* — Add a new row
• *update* — Update a task's status/field
• *help* — Show this menu"""


def get_session(phone):
    if phone not in sessions:
        sessions[phone] = {"state": "idle", "data": {}}
    return sessions[phone]


def reset_session(phone):
    sessions[phone] = {"state": "idle", "data": {}}


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    resp = MessagingResponse()
    msg = resp.message()

    session = get_session(sender)
    state = session["state"]
    reply = handle_message(incoming_msg, sender, session, state)
    msg.body(reply)
    return str(resp)


def handle_message(text, sender, session, state):
    cmd = text.lower()

    # ── IDLE state — top-level commands ──────────────────────────────────────
    if state == "idle":
        if cmd in ("hi", "hello", "hey", "start"):
            return HELP_TEXT

        elif cmd == "help":
            return HELP_TEXT

        elif cmd == "show" or (len(cmd.split()) == 2 and cmd.split()[0] == "show" and cmd.split()[1].isdigit()):
            rows = get_all_rows()
            if not rows:
                return "No data found in the sheet."
            data_rows = rows[1:]
            parts = cmd.split()
            page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            page_size = 10
            total = len(data_rows)
            total_pages = (total + page_size - 1) // page_size
            page = max(1, min(page, total_pages))
            start = (page - 1) * page_size
            end = start + page_size
            lines = [f"Tasks (Page {page}/{total_pages}):\n"]
            for i, row in enumerate(data_rows[start:end], start=start + 1):
                task = row[1] if len(row) > 1 else "?"
                status = row[2] if len(row) > 2 else "?"
                priority = row[3] if len(row) > 3 else "?"
                lines.append(f"{i}. {task} - {status} | {priority}")
            if page < total_pages:
                lines.append(f"\nSend 'show {page + 1}' for next page.")
            lines.append("\nSend 'add' or 'update' to make changes.")
            return "\n".join(lines)

        elif cmd == "add":
            session["state"] = "add_category"
            return ("➕ *Add New Task*\n\n"
                    "Step 1/5 — What *category* does this task belong to?\n"
                    "(e.g. Inventory, Pricing, Advertising)")

        elif cmd == "update":
            rows = get_all_rows()
            if not rows:
                return "📭 Sheet is empty."
            lines = ["✏️ *Which task do you want to update?*\n",
                     "Reply with the task number:\n"]
            for i, row in enumerate(rows[1:], start=1):
                task = row[1] if len(row) > 1 else "?"
                lines.append(f"{i}. {task}")
            session["state"] = "update_pick_row"
            session["data"]["rows"] = rows
            return "\n".join(lines)

        else:
            return "🤖 I didn't understand that.\n\nReply *help* to see commands."

    # ── ADD flow ──────────────────────────────────────────────────────────────
    elif state == "add_category":
        session["data"]["category"] = text
        session["state"] = "add_task"
        return "Step 2/5 — What is the *task name*?"

    elif state == "add_task":
        session["data"]["task"] = text
        session["state"] = "add_status"
        return ("Step 3/5 — What is the *status*?\n"
                "(Pending / In Progress / Done / Ongoing)")

    elif state == "add_status":
        session["data"]["status"] = text
        session["state"] = "add_priority"
        return "Step 4/5 — What is the *priority*?\n(High / Medium / Low)"

    elif state == "add_priority":
        session["data"]["priority"] = text
        session["state"] = "add_owner"
        return "Step 5/5 — Who is the *owner*?\n(e.g. You / Marketing / Ops)"

    elif state == "add_owner":
        session["data"]["owner"] = text
        d = session["data"]
        new_row = [
            d.get("category", ""),
            d.get("task", ""),
            d.get("status", "Pending"),
            d.get("priority", "Medium"),
            d.get("owner", ""),
            "",  # Frequency — blank for now
            "",  # KPI/Goal — blank for now
        ]
        success = append_row(new_row)
        reset_session(sender)
        if success:
            return (f"✅ *Task added!*\n\n"
                    f"📁 Category: {new_row[0]}\n"
                    f"📝 Task: {new_row[1]}\n"
                    f"🔄 Status: {new_row[2]}\n"
                    f"⚡ Priority: {new_row[3]}\n"
                    f"👤 Owner: {new_row[4]}")
        else:
            return "❌ Failed to add the task. Please try again."

    # ── UPDATE flow ───────────────────────────────────────────────────────────
    elif state == "update_pick_row":
        rows = session["data"].get("rows", [])
        try:
            row_num = int(text)
            actual_row_index = row_num  # row 1 = index 1 (header is index 0)
            chosen = rows[actual_row_index]
            session["data"]["row_index"] = actual_row_index
            session["data"]["chosen_row"] = chosen
            session["state"] = "update_pick_field"

            task_name = chosen[1] if len(chosen) > 1 else "?"
            return (f"✏️ Editing: *{task_name}*\n\n"
                    "Which field do you want to update?\n"
                    "1. Status\n"
                    "2. Priority\n"
                    "3. Owner\n\n"
                    "Reply with the number.")
        except (ValueError, IndexError):
            reset_session(sender)
            return "❌ Invalid number. Reply *update* to try again."

    elif state == "update_pick_field":
        field_map = {"1": (2, "Status"), "2": (3, "Priority"), "3": (4, "Owner")}
        if text not in field_map:
            return "Please reply with 1, 2, or 3."
        col_index, field_name = field_map[text]
        session["data"]["col_index"] = col_index
        session["data"]["field_name"] = field_name
        session["state"] = "update_enter_value"
        return f"What should the new *{field_name}* be?"

    elif state == "update_enter_value":
        row_index = session["data"]["row_index"]
        col_index = session["data"]["col_index"]
        field_name = session["data"]["field_name"]
        task_name = session["data"]["chosen_row"][1] if len(session["data"]["chosen_row"]) > 1 else "?"

        success = update_cell(row_index + 1, col_index + 1, text)  # +1 for 1-indexed sheets
        reset_session(sender)
        if success:
            return (f"✅ Updated!\n\n"
                    f"📝 Task: *{task_name}*\n"
                    f"🔧 {field_name}: {text}")
        else:
            return "❌ Update failed. Please try again."

    # Fallback
    reset_session(sender)
    return "Something went wrong. Reply *help* to start over."


if __name__ == "__main__":
    app.run(debug=True, port=5000)
