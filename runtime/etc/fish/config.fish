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
