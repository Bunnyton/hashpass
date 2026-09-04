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

# Live interaction with the host. When hashpass runs a task it sets HP_PORT to a host loopback
# port; we talk to it over the container's shared loopback via bash's /dev/tcp (no mount, nothing
# visible in the container). At startup we ask for the greeting ("hello"); after every command we
# send it ("cmd <base64>") so the host can react/grade/hint and print the result live. The host
# does all the work and holds the answers -- only text to display crosses back in.
if set -q HP_PORT
    # After every command, ship it to the host WITH its output. script(1) (see hp-fish) records the
    # terminal to $HOME/.hp-typescript; we read the delta written since the previous command (that
    # command's output), base64 it, and send `cmd <command> <output>`. __hp_off tracks how far we
    # have read; after hp-io streams the host's reply (also recorded) we advance __hp_off past it so
    # the reply text does not leak into the NEXT command's output. Output is capped to 64 KiB. When
    # no typescript exists (script did not start -- plain fish fallback), out is empty: the host
    # then just gets `cmd <command>`, i.e. the previous behaviour, and output hints simply do not fire.
    set -g __hp_off 0
    function __hp_postexec --on-event fish_postexec
        set -l log "$HOME/.hp-typescript"
        set -l size (stat -c %s "$log" 2>/dev/null; or echo 0)
        set -l out ''
        if test $size -gt $__hp_off
            set out (tail -c +(math $__hp_off + 1) "$log" 2>/dev/null | tail -c 65536 | base64 -w0)
        end
        set -g __hp_off $size
        hp-io "cmd "(printf '%s' $argv[1] | base64 -w0)" "$out 2>/dev/null
        set -g __hp_off (stat -c %s "$log" 2>/dev/null; or echo $size)
    end
    hp-io hello 2>/dev/null
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
