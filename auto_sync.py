
import os
import time
import threading
import subprocess

from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

ROOT = Path(__file__).resolve().parent
BRANCH = "main"
DEBOUNCE_SECONDS = 3
PULL_INTERVAL = 10

sync_lock = threading.Lock()
last_change = 0
dirty = False


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60
    )


def show_result(result):
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


def sync():
    global dirty

    if not sync_lock.acquire(blocking=False):
        return

    try:
        branch = git("branch", "--show-current")

        if branch.stdout.strip() != BRANCH:
            print(f"[ERROR] Switch to {BRANCH} branch first.")
            return

        status = git("status", "--porcelain")

        if status.returncode != 0:
            show_result(status)
            return

        # Commit local changes first
        if status.stdout.strip():
            print("\n[+] Saving local changes...")

            add = git("add", "-A")
            if add.returncode != 0:
                show_result(add)
                return

            commit = git(
                "commit",
                "-m",
                f"Auto-sync: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if commit.returncode != 0:
                show_result(commit)
                return

            show_result(commit)

        # Pull remote changes and rebase local commits
        print("[+] Checking GitHub updates...")

        pull = git("pull", "--rebase", "origin", BRANCH)

        if pull.returncode != 0:
            print("[CONFLICT] Pull/rebase failed. Automatic sync paused.")
            show_result(pull)
            return

        # Retry push if another person pushed at the same time
        for attempt in range(3):
            push = git("push", "origin", BRANCH)

            if push.returncode == 0:
                if push.stdout.strip():
                    show_result(push)
                print("[SYNCED] Your project is up to date.")
                dirty = False
                return

            print(f"[+] Push attempt {attempt + 1} failed. Retrying pull...")
            show_result(push)

            pull = git("pull", "--rebase", "origin", BRANCH)

            if pull.returncode != 0:
                print("[CONFLICT] Resolve the conflict manually.")
                show_result(pull)
                return

        print("[ERROR] Could not push after 3 attempts.")

    except subprocess.TimeoutExpired:
        print("[ERROR] Git command timed out.")

    finally:
        sync_lock.release()


class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        global last_change, dirty

        if event.is_directory:
            return

        path = Path(event.src_path)

        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            return

        ignored = {".git", ".venv", "__pycache__"}

        if any(part in ignored for part in relative.parts):
            return

        if path.suffix == ".pyc":
            return

        dirty = True
        last_change = time.monotonic()


def main():
    global dirty

    print("=" * 45)
    print("       HACK TRICKY AUTO SYNC")
    print("=" * 45)
    print(f"Watching: {ROOT}")
    print("Press Ctrl+C to stop.\n")

    # Ignore local Python environment files
    exclude = ROOT / ".git" / "info" / "exclude"

    with exclude.open("a") as f:
        f.write("\n.venv/\n__pycache__/\n*.pyc\n")

    observer = Observer()
    observer.schedule(ChangeHandler(), str(ROOT), recursive=True)
    observer.start()

    last_pull = 0

    try:
        while True:
            now = time.monotonic()

            if dirty and now - last_change >= DEBOUNCE_SECONDS:
                sync()

            elif now - last_pull >= PULL_INTERVAL:
                sync()
                last_pull = now

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[+] Stopping auto sync...")

    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
