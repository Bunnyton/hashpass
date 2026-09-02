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

# Per-command grading. When hashpass binds its signal dir at /.hp-sig (interactive task run),
# ping the host after every command and print whatever it reports (a stage pass + the next
# goal). The host does the grading and holds the answers -- only result TEXT crosses back in,
# so nothing secret is ever exposed in the student's console.
if test -d /.hp-sig
    function __hp_postexec --on-event fish_postexec
        echo 1 > /.hp-sig/tick
        for i in (seq 1 80)          # wait up to ~4s for the host to grade + answer
            if test -f /.hp-sig/result
                cat /.hp-sig/result   # a stage-pass message, or empty (nothing to report)
                rm -f /.hp-sig/result
                break
            end
            sleep 0.05
        end
    end
end

# `exit` finishes the task: it powers the machine off, which returns control to hashpass on
# the host, where the stages are graded. Defined as a function (shadowing fish's builtin) so it
# works in a SINGLE keystroke even with background jobs still running -- the builtin would warn
# ("There are still jobs active") and refuse to leave on the first try, which looks like the
# task was ignored. The shutdown terminates this shell within a moment.
function exit --description 'finish the task and close the machine (your work is graded on exit)'
    systemctl poweroff 2>/dev/null
    command sleep 3600  # block so no stray prompt flashes before the shutdown kills us
end
