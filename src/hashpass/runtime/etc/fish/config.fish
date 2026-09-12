# hashpass base image — a friendly, colourful interactive fish shell.
# Syntax highlighting, autosuggestions and completions are fish defaults; this sets a clean
# two-tone prompt (cwd + a red mark on error), a welcome banner, and a few handy aliases.

# Welcome banner: an ASCII "hashpass" for the plain image/edit console. A graded task (HP_PORT)
# drives its own intro, so stay quiet there.
function fish_greeting
    set -q HP_PORT; and return
    set_color brmagenta
    cat /etc/hp-banner 2>/dev/null
    set_color normal
end

# Handy aliases (ништячки) — coloured, human-friendly listings.
if status is-interactive
    alias ll 'ls -alh --color=auto'
    alias la 'ls -A --color=auto'
    alias l 'ls -CF --color=auto'
end

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

    # Command policy (allow/deny): BEFORE every command we ask the host for the current stage's
    # policy and, if the command is not permitted, shadow its name with a function that refuses and
    # returns non-zero -- so it does not run at all ("в принципе не выполняется"). A function defined
    # in fish_preexec shadows the binary/builtin for THIS very run; __hp_unshadow erases it right
    # after, so the next command is judged fresh against the (possibly changed) stage policy.
    # `allow` = only these bases pass (plus neutral + cd/exit); `deny` = these bases are blocked.
    # The refusal body uses `builtin echo` (NOT `echo`) so shadowing `echo` itself does not recurse;
    # and we blank fish_title, which otherwise runs `echo` mid-command and would hit that shadow.
    # Message is plain text, no emoji.
    function fish_title; end
    set -g __hp_shadow
    function __hp_guard --on-event fish_preexec
        set -e __hp_shadow
        set -l pol (hp-io policy 2>/dev/null)
        test -n "$pol"; or return
        set -l parts (string split ';' -- $pol)
        set -l allow; test -n "$parts[1]"; and set allow (string split ',' -- $parts[1])
        set -l deny; test -n "$parts[2]"; and set deny (string split ',' -- $parts[2])
        set -l neutral; test -n "$parts[3]"; and set neutral (string split ',' -- $parts[3])
        test (count $allow) -gt 0 -o (count $deny) -gt 0; or return   # no policy -> nothing to block
        set -l flat (string replace -ra '(\|\||&&|;|\|)' \n -- $argv[1])
        for seg in (string split \n -- $flat)
            set -l toks (string split -n ' ' -- (string trim -- $seg))
            test (count $toks) -gt 0; or continue
            set -l b $toks[1]
            test "$b" = sudo -a (count $toks) -ge 2; and set b $toks[2]
            test -n "$b"; or continue
            set -l block 0
            if test (count $deny) -gt 0; and contains -- $b $deny
                set block 1
            else if test (count $allow) -gt 0; and not contains -- $b $allow $neutral cd exit
                set block 1
            end
            if test $block -eq 1
                function $b --inherit-variable b; builtin echo "Команда «$b» запрещена."; return 1; end
                set -g __hp_shadow $__hp_shadow $b
            end
        end
    end
    function __hp_unshadow --on-event fish_postexec
        for f in $__hp_shadow
            functions -e $f
        end
        set -e __hp_shadow
    end

    # Typing timing (anti-bot): mark when the prompt is drawn and when the command is submitted,
    # so the host can estimate typing speed (chars/sec) and flag pasted commands.
    function __hp_mark_prompt --on-event fish_prompt
        set -g __hp_prompt_t (date +%s.%N)
    end
    function __hp_mark_submit --on-event fish_preexec
        set -g __hp_submit_t (date +%s.%N)
    end

    function __hp_postexec --on-event fish_postexec
        set -l log "$HOME/.hp-typescript"
        set -l size (stat -c %s "$log" 2>/dev/null; or echo 0)
        set -l out ''
        if test $size -gt $__hp_off
            set out (tail -c +(math $__hp_off + 1) "$log" 2>/dev/null | tail -c 65536 | base64 -w0)
        end
        set -g __hp_off $size
        set -l typing ''
        if set -q __hp_prompt_t; and set -q __hp_submit_t
            set typing (math "$__hp_submit_t - $__hp_prompt_t" 2>/dev/null)
        end
        hp-io "cmd "(printf '%s' $argv[1] | base64 -w0)" "$out" "$typing 2>/dev/null
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
