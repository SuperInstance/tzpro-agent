"""
cascade/notify.py

Sends Markdown briefings from the cascade perception daemon to Telegram.

SETUP:
1. Create a bot via @BotFather on Telegram to get your TELEGRAM_BOT_TOKEN.
2. Get your Chat ID (use @userinfobot or similar) to get your TELEGRAM_CHAT_ID.
3. Set these as environment variables:
   export TELEGRAM_BOT_TOKEN='***'
   export TELEGRAM_CHAT_ID='your_chat_id_here'

CONFIGURATION:
- CASCADE_NOTIFY_QUIET_START: HH:MM (e.g., 22:00) - Start of quiet hours.
- CASCADE_NOTIFY_QUIET_END: HH:MM (e.g., 07:00) - End of quiet hours.
  If current time is within this window, briefings are marked as 'pending' in the state file
  and will be sent once quiet hours end.

USAGE:
- Process new briefings: python -m cascade.notify --dir /path/to/briefings
- Test credentials: python -m cascade.notify --test
"""

import os
import json
import time
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, time as dt_time

def _is_quiet_hours() -> bool:
    start_str = os.getenv("CASCADE_NOTIFY_QUIET_START")
    end_str = os.getenv("CASCADE_NOTIFY_QUIET_END")
    if not start_str or not end_str:
        return False
    
    try:
        now = datetime.now().time()
        start = dt_time.fromisoformat(start_str)
        end = dt_time.fromisoformat(end_str)
        
        if start <= end:
            return start <= now <= end
        else:  # Over midnight (e.g., 22:00 to 07:00)
            return now >= start or now <= end
    except ValueError:
        return False

def send_briefing(briefing_path: str | Path) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print(f"WARNING: Missing Telegram credentials (TOKEN or CHAT_ID).")
        return False

    try:
        with open(briefing_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"ERROR: Could not read briefing file {briefing_path}: {e}")
        return False

    # Split into 4000 char chunks (Telegram limit is ~4096)
    chunks = [content[i:i+4000] for i in range(0, len(content), 4000)]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    for chunk in chunks:
        data = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": ""  # Ensure no markdown parsing
        }
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data)
        
        try:
            with urllib.request.urlopen(req) as res:
                if res.status != 200:
                    print(f"ERROR: Telegram API returned {res.status}")
                    return False
        except Exception as e:
            print(f"ERROR: Telegram send failed: {e}")
            return False
        
        if len(chunks) > 1:
            time.sleep(1)
            
    return True

def notify_new_briefings(state_file: Path, briefings_dir: Path) -> int:
    state_file = Path(state_file).resolve()
    briefings_dir = Path(briefings_dir).resolve()
    
    if not briefings_dir.is_dir():
        print(f"ERROR: {briefings_dir} is not a directory.")
        return 0

    # Load state
    state = {"sent": [], "pending": []}
    if state_file.exists():
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except Exception as e:
            print(f"WARNING: Could not read state file: {e}")

    # Find all .md files in directory
    current_files = sorted([f.name for f in briefings_dir.glob("*.md")])
    
    # Identify new files
    new_files = [f for f in current_files if f not in state["sent"] and f not in state["pending"]]
    
    count_sent = 0
    is_quiet = _is_quiet_hours()
    
    # Process pending first
    # We must maintain the current state but update it as we go
    to_process = state["pending"] + new_files
    state["pending"] = [] # Reset to rebuild from items not sent/not quiet

    # Create a working set of pending names to ensure we don't lose them
    unprocessed_pending = []

    for filename in to_process:
        f_path = briefings_dir / filename
        if not f_path.exists():
            continue
            
        if is_quiet:
            state["pending"].append(filename)
            continue
            
        if send_briefing(f_path):
            state["sent"].append(filename)
            count_sent += 1
        else:
            state["pending"].append(filename)

    # Atomic write state
    temp_state = state_file.with_suffix(".tmp")
    try:
        with open(temp_state, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(temp_state, state_file)
    except Exception as e:
        print(f"ERROR: Failed to save state: {e}")
        if temp_state.exists():
            os.remove(temp_state)

    return count_sent

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, help="Directory containing briefings")
    parser.add_argument("--test", action="store_true", help="Test Telegram connection")
    args = parser.parse_args()

    if args.test:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
            exit(1)
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as tmp:
            tmp.write("cascade notify: link OK")
            tmp_path = tmp.name
            
        try:
            if send_briefing(tmp_path):
                print("Test successful: Connection OK.")
            else:
                print("Test failed.")
                exit(1)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    elif args.dir:
        state_path = Path.cwd() / ".cascade_notify_state.json"
        count = notify_new_briefings(state_path, Path(args.dir))
        print(f"Processed. Sent {count} new briefings.")
    else:
        parser.print_help()
