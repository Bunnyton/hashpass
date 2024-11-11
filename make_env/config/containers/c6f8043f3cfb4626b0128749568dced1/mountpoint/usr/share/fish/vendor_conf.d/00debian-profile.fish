# [Debian] Synchronize default PATH with /etc/profile
if not set -q FISH_UNIT_TESTS_RUNNING
    if status is-login
        if test (/usr/bin/id -u) = 0
            fish_add_path -aP /usr/local/sbin
            fish_add_path -aP /usr/local/bin
            fish_add_path -aP /usr/sbin
            fish_add_path -aP /usr/bin
            fish_add_path -aP /sbin
            fish_add_path -aP /bin
        else
            fish_add_path -aP /usr/local/bin
            fish_add_path -aP /usr/bin
            fish_add_path -aP /bin
            fish_add_path -aP /usr/local/games
            fish_add_path -aP /usr/games
        end
    end
end
