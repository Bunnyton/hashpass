complete -c test -d 'condition evaluation utility' --force-files
complete -c test -k -f -a ! -d "Negate expression"
complete -c test -k -f -s a -d "Logical AND"
complete -c test -k -f -s o -d "Logical OR"
complete -c test -k -f -s n -d "String length is non-zero"
complete -c test -k -f -s z -d "String length is zero"
complete -c test -k -f -a = -d "Strings are identical"
complete -c test -k -f -a != -d "Strings are not identical"
complete -c test -k -f -o eq -d "Numbers are equal"
complete -c test -k -f -o ge -d "Left number >= right number"
complete -c test -k -f -o gt -d "Left number > right number"
complete -c test -k -f -o le -d "Left number <= right number"
complete -c test -k -f -o lt -d "Left number < right number"
complete -c test -k -f -o ne -d "Left number != right number"
complete -c test -k -o ef -d "Left file equal to right file"
complete -c test -k -o nt -d "Left file newer than right file"
complete -c test -k -o ot -d "Left file older than right file"
complete -c test -k -s b -r -d "File is block device"
complete -c test -k -s c -r -d "File is character device"
complete -c test -k -s d -r -d "File is directory"
complete -c test -k -s e -r -d "File exists"
complete -c test -k -s f -r -d "File is regular"
complete -c test -k -s g -r -d "File is set-group-ID"
complete -c test -k -s G -r -d "File owned by our effective group ID"
complete -c test -k -s L -r -d "File is a symlink"
complete -c test -k -s O -r -d "File owned by our effective user ID"
complete -c test -k -s p -r -d "File is a named pipe"
complete -c test -k -s r -r -d "File is readable"
complete -c test -k -s s -r -d "File size is non-zero"
complete -c test -k -s S -r -d "File is a socket"
complete -c test -k -f -s t -d "FD is a terminal"
complete -c test -k -s u -r -d "File set-user-ID bit is set"
complete -c test -k -s w -r -d "File is writable"
complete -c test -k -s x -r -d "File is executable"