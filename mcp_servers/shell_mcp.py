from mcp.server.fastmcp import FastMCP
import subprocess
import shlex
import re
import os

ALLOWLIST = {
    # file operations
    "ls", "cat", "head", "tail", "wc", "nl", "od", "xxd",
    # directory
    "pwd", "tree", "du", "df", "stat", "realpath", "readlink", "dirname", "basename",
    # text processing
    "echo", "grep", "sort", "uniq", "cut", "tr", "diff", "comm", "tee",
    "fold", "pr", "expand", "unexpand", "fmt",
    # file info
    "file", "which", "type",
    # system info
    "whoami", "id", "who", "w", "last", "date", "cal", "uptime", "uname",
    "hostname", "env", "printenv", "nproc", "free", "lscpu", "lsblk",
    "lsusb", "lspci", "lshw",
    # process
    "ps", "top",
    # network
    "ss", "ip", "hostname",
    # compression (read-only)
    "tar", "gzcat", "zcat", "bzcat", "xzcat",
}

mcp = FastMCP("shell-mcp-uv")


def is_command_allowed(full_command: str) -> tuple[bool, str]:
    cmd_stripped = full_command.strip()
    if not cmd_stripped:
        return False, "Empty command"

    # Block shell metacharacters that allow multi-command execution
    forbidden = re.compile(r'[;&`$\n\\!(){}]')
    if forbidden.search(cmd_stripped):
        return False, "Shell metacharacters not allowed (;, &, `, $, \\, !, (), {})"

    # Block redirects to /dev, /proc, /sys
    if re.search(r'(>|>>)\s*(/dev/|/proc/|/sys/)', cmd_stripped):
        return False, "Redirect to system paths blocked"

    # Split pipes and check each segment
    for segment in cmd_stripped.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        try:
            parts = shlex.split(segment)
        except ValueError:
            return False, f"Invalid shell quoting in segment: {segment}"
        if not parts:
            continue
        base_cmd = os.path.basename(parts[0])
        if base_cmd not in ALLOWLIST:
            return False, f"Command '{base_cmd}' not in allowlist"
    return True, ""


@mcp.tool()
def run_shell(command: str, timeout: int = 30):
    """Run a shell command securely using an allowlist approach"""
    allowed, reason = is_command_allowed(command)
    if not allowed:
        return {"error": f"Blocked: {reason}"}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}
