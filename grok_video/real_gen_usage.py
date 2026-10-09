"""Read the SuperGrok weekly usage meter (whole percent) from the grok TUI `/usage` panel, via a throwaway tmux
session. Never reads or prints credentials. Returns None if the meter can't be read."""
import re, subprocess, time, uuid
import common_gv as G


def usage_pct():
    name = 'gu' + uuid.uuid4().hex[:6]
    try:
        subprocess.run(['tmux', 'new-session', '-d', '-s', name, '-x', '160', '-y', '50', '-c', '/tmp', G.GROK], check=True,
                       timeout=20)
        time.sleep(6)
        subprocess.run(['tmux', 'send-keys', '-t', name, '/usage', 'Enter'], check=True, timeout=10)
        for _ in range(6):
            time.sleep(2)
            out = subprocess.run(['tmux', 'capture-pane', '-p', '-t', name], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r'Weekly limit.*?(\d{1,3})%', out, re.S)
            if m:
                return int(m.group(1))
        return None
    except Exception:
        return None
    finally:
        subprocess.run(['tmux', 'kill-session', '-t', name], capture_output=True)
