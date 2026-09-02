# hashpass base image — a friendly, colourful interactive fish shell.
# Syntax highlighting, autosuggestions and completions are fish defaults; this just
# quiets the banner and sets a clean two-tone prompt (cwd + a red mark on error).
set -g fish_greeting ''

function fish_prompt
    set -l last $status
    set_color brblue
    echo -n (prompt_pwd)
    if test $last -ne 0
        set_color brred
        echo -n ' ✗'
    end
    set_color brgreen
    echo -n ' ❯ '
    set_color normal
end

# Per-command grading. When hashpass runs a task it sets HP_PORT to a host loopback port; after
# every command, ping it (over the container's shared loopback, via bash's /dev/tcp -- no mount,
# nothing visible in the container) and print whatever the host reports (a stage pass + the next
# goal). The host does the grading and holds the answers -- only result TEXT crosses back in.
if set -q HP_PORT
    function __hp_postexec --on-event fish_postexec
        bash -c "exec 3<>/dev/tcp/127.0.0.1/$HP_PORT 2>/dev/null && echo tick >&3 && cat <&3" 2>/dev/null
    end
end

# `exit` finishes the task: it powers the machine off, which returns control to hashpass on
# the host, where the stages are graded. Defined as a function (shadowing fish's builtin) so it
# works in a SINGLE keystroke even with background jobs still running -- the builtin would warn
# ("There are still jobs active") and refuse to leave on the first try, which looks like the
# task was ignored. The shutdown terminates this shell within a moment.
function exit --description 'finish the task and close the machine (your work is graded on exit)'
    for pid in (jobs -p)
        disown $pid 2>/dev/null   # release background jobs so fish leaves on the FIRST try
    end
    builtin exit $argv            # hp-console (root) powers the machine off once fish exits
end
