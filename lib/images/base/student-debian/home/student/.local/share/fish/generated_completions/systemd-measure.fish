# systemd-measure
# Autogenerated from man page /usr/share/man/man1/systemd-measure.1.gz
complete -c systemd-measure -l linux -l osrel -l cmdline -l initrd -l splash -l dtb -l pcrpkey -d 'When used with the calculate or sign verb, configures the files to read the u…'
complete -c systemd-measure -l current -d 'When used with the calculate or sign verb, takes the PCR 11 values currently …'
complete -c systemd-measure -l bank -d 'Controls the PCR banks to pre-calculate the PCR values for \\(en in case calcu…'
complete -c systemd-measure -l private-key -l public-key -d 'These switches take paths to a pair of PEM encoded RSA key files, for use wit…'
complete -c systemd-measure -l tpm2-device -d 'Controls which TPM2 device to use'
complete -c systemd-measure -l phase -d 'Controls which boot phases to calculate expected PCR 11 values for'
complete -c systemd-measure -l json -d 'Shows output formatted as JSON'
complete -c systemd-measure -l no-pager -d 'Do not pipe output into a pager'
complete -c systemd-measure -s h -l help -d 'Print a short help text and exit'
complete -c systemd-measure -l version -d 'Print a short version string and exit'
complete -c systemd-measure -l pcr-bank -d 'systemd-creds(1)) or LUKS volumes (see systemd-cryptsetup@. service(8))'
