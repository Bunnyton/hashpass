# vi
# Autogenerated from man page /usr/share/man/man1/vi.1.gz
complete -c vi -s c -d '{command} will be executed after the first file has been read'
complete -c vi -s S -d '{file} will be sourced after the first file has been read'
complete -c vi -l cmd -d 'Like using "-c", but the command is executed just before processing any vimrc…'
complete -c vi -s A -d 'If  Vim has been compiled with ARABIC support for editing right-to-left orien…'
complete -c vi -s b -d 'Binary mode'
complete -c vi -s C -d 'Compatible.   Set the \'compatible\' option'
complete -c vi -s d -d 'Start in diff mode.  There should between two to eight file name arguments'
complete -c vi -s D -d Debugging
complete -c vi -s e -d 'Start  Vim in Ex mode, just like the executable was called "ex"'
complete -c vi -s E -d 'Start  Vim in improved Ex mode, just like the executable was called "exim"'
complete -c vi -s f -d Foreground
complete -c vi -l nofork -d Foreground
complete -c vi -s F -d 'If  Vim has been compiled with FKMAP support for editing right-to-left orient…'
complete -c vi -s g -d 'If  Vim has been compiled with GUI support, this option enables the GUI'
complete -c vi -s h -d 'Give a bit of help about the command line arguments and options'
complete -c vi -s H -d 'If  Vim has been compiled with RIGHTLEFT support for editing right-to-left or…'
complete -c vi -s i -d 'Specifies the filename to use when reading or writing the viminfo file, inste…'
complete -c vi -s L -d 'Same as -r'
complete -c vi -s l -d 'Lisp mode.  Sets the \'lisp\' and \'showmatch\' options on'
complete -c vi -s m -d 'Modifying files is disabled.  Resets the \'write\' option'
complete -c vi -s M -d 'Modifications not allowed'
complete -c vi -s N -d 'No-compatible mode.   Resets the \'compatible\' option'
complete -c vi -s n -d 'No swap file will be used.  Recovery after a crash will be impossible'
complete -c vi -o nb -d 'Become an editor server for NetBeans.   See the docs for details'
complete -c vi -s o -d 'Open N windows stacked.  When N is omitted, open one window for each file'
complete -c vi -s O -d 'Open N windows side by side'
complete -c vi -s p -d 'Open N tab pages.  When N is omitted, open one tab page for each file'
complete -c vi -s R -d 'Read-only mode.  The \'readonly\' option will be set'
complete -c vi -s r -d 'List swap files, with information about using them for recovery'
complete -c vi -s s -d 'Silent mode'
complete -c vi -s T -d 'Tells  Vim the name of the terminal you are using'
complete -c vi -s u -d 'Use the commands in the file {vimrc} for initializations'
complete -c vi -s U -d 'Use the commands in the file {gvimrc} for GUI initializations'
complete -c vi -s V -d Verbose
complete -c vi -s v -d 'Start  Vim in Vi mode, just like the executable was called "vi"'
complete -c vi -s w -d 'All the characters that you type are recorded in the file {scriptout}, until …'
complete -c vi -s W -d 'Like -w, but an existing file is overwritten'
complete -c vi -s x -d 'Use encryption when writing files.   Will prompt for a crypt key'
complete -c vi -s X -d 'Don\'t connect to the X server'
complete -c vi -s y -d 'Start  Vim in easy mode, just like the executable was called "evim" or "eview"'
complete -c vi -s Z -d 'Restricted mode.   Works like the executable starts with "r"'
complete -c vi -l clean -d 'Do not use any personal configuration (vimrc, plugins, etc. )'
complete -c vi -l echo-wid -d 'GTK GUI only: Echo the Window ID on stdout'
complete -c vi -l help -d 'Give a help message and exit, just like "-h"'
complete -c vi -l literal -d 'Take file name arguments literally, do not expand wildcards'
complete -c vi -l noplugin -d 'Skip loading plugins.   Implied by -u NONE'
complete -c vi -l remote -d 'Connect to a Vim server and make it edit the files given in the rest of the a…'
complete -c vi -l remote-expr -d 'Connect to a Vim server, evaluate {expr} in it and print the result on stdout'
complete -c vi -l remote-send -d 'Connect to a Vim server and send {keys} to it'
complete -c vi -l remote-silent -d 'As --remote, but without the warning when no server is found'
complete -c vi -l remote-wait -d 'As --remote, but Vim does not exit until the files have been edited'
complete -c vi -l remote-wait-silent -d 'As --remote-wait, but without the warning when no server is found'
complete -c vi -l serverlist -d 'List the names of all Vim servers that can be found'
complete -c vi -l servername -d 'Use {name} as the server name'
complete -c vi -l socketid -d 'GTK GUI only: Use the GtkPlug mechanism to run gvim in another window'
complete -c vi -l startuptime -d 'During startup write timing messages to the file {fname}'
complete -c vi -s t -d 'The file to edit and the initial cursor position depends on a "tag", a sort o…'
complete -c vi -s q -d 'Start in quickFix mode'
complete -c vi -l version -d 'Print version information and exit'
