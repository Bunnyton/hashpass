#dupload
complete -c dupload -s h -l help -d (_ "Display help and exit")
complete -c dupload -s f -l force -d (_ "Upload regardless of the transfers logged as already completed")
complete -c dupload -s k -l keep -d (_ "Ignore packages whose MD5sums don't match")
complete -c dupload -s c -l configfile -d (_ "Read ./dupload.conf")
complete -c dupload -l no -d (_ "Dry-run")
complete -c dupload -l nomail -d (_ "Suppress announcement")
complete -c dupload -l mailonly -d (_ "Dry-run and real announcement")
complete -c dupload -l noarchive -d (_ "Add an anti-archival header")
complete -c dupload -s p -l print -d (_ "Print config")
complete -c dupload -s q -l quiet -d (_ "Quiet")
complete -c dupload -s t -l to -x -a "(__dupload_hosts)" -d (_ "Nickname of target site")
complete -c dupload -s V -l version -d (_ "Display version information and exit")
complete -c dupload -x -a "(__fish_complete_suffix .changes)"

function __dupload_hosts -d "List hosts for dupload"
  set -l nicks
  set -l hosts
  for n in (awk -F "'" '/\$cfg{/ {print $2}' /etc/dupload.conf $HOME/.dupload.conf | uniq);
    set nicks $nicks $n;
  end
  for h in (awk -F "=" '/('\''fqdn'\''| *fqdn *=)/ {print $2}' /etc/dupload.conf $HOME/.dupload.conf | cut -d"'" -f2 | cut -d'"' -f2);
    set hosts $hosts $h;
  end
  set -l i 1
  set -l max (count $nicks)
  while test $i -le $max;
    echo (printf "%s\t%s" $nicks[$i] $hosts[$i])
    set i (echo "$i + 1" | bc)
  end
  return
end
