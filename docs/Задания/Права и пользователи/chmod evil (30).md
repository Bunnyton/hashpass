
```
#!/bin/bash


key="pass"

declare -A perm_table

perm_table["0"]="---"
perm_table["1"]="--x"
perm_table["2"]="-w-"
perm_table["3"]="-wx"
perm_table["4"]="r--"
perm_table["5"]="r-x"
perm_table["6"]="rw-"
perm_table["7"]="rwx"

function wait_perms(){

        filename="./$(echo $1 | sed "s/\.\///g")"
        type=$2
        perms=$3
        own=$4
        group=$5
        mode=$6

        wait_str="-"
        if [[ $type == "dir" ]]
        then
                wait_str="d"
        fi

        for i in $(seq 1 3)
        do
                perm=$(echo "$perms" | cut -c$i)
                wait_str="$wait_str${perm_table[$perm]}"
        done

        wait_str="$wait_str $own $group $filename"

        echo "Сделайте так, чтобы при команде ls -l получить следующие права, владельца, группу и имя файла соответственно:"
        echo "$wait_str"

        if [[ $mode == "full" ]]
        then
                echo "Используйте только побитовую запись прав для chmod (chmod 777)"
        else
                echo "Используйте только относительную запись прав для chmod (chmod +x)"
        fi

        echo ""


        rm ~/.bash_history 2> /dev/null

        while [[ "$(ls -la $filename 2> /dev/null | cut -d ' ' -f 1,3,4 ) $filename" != $wait_str ]]
        do
                sleep 1
        done

        if [[ $mode == "full" ]]
        then
                if [[ ! -z $(cat ~/.bash_history | grep "chmod" | grep -P "\+|\-") ]]
                then
                        echo "Придется начать сначала..."
                        echo "./task.sh &"
                        exit 1
                fi
        else
                if [[ ! -z $(cat ~/.bash_history | grep "chmod" | grep -vP "\+|\-") ]]
                then
                        echo "Придется начать сначала..."
                        echo "./task.sh &"
                        exit 1
                fi
        fi
}

wait_perms ./test file 111 $(whoami) $(whoami) full
wait_perms ./test file 123 $(whoami) $(whoami) simple
wait_perms ./test file 625 $(whoami) $(whoami) full
wait_perms ./test file 725 $(whoami) $(whoami) full
wait_perms ./test file 123 $(whoami) $(whoami) simple
wait_perms ./test file 325 $(whoami) $(whoami) simple

wait_perms ./dir/dir/file file 701 $(whoami) $(whoami) full
wait_perms ./test1 file 000 $(whoami) minimal simple
wait_perms ./test2 file 725 $(whoami) $(whoami) full
wait_perms ./test3 file 123 $(whoami) minimal simple
wait_perms ./test4 file 325 $(whoami) $(whoami) simple
wait_perms ./dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir/dir file 010 $(whoami) minimal simple
wait_perms ./test1 file 010 $(whoami) $(whoami) full
wait_perms ./test2 file 755 $(whoami) $(whoami) full
wait_perms ./test3 file 723 $(whoami) minimal full
wait_perms ./test4 file 725 $(whoami) $(whoami) full
wait_perms ./test4 file 767 $(whoami) $(whoami) full


echo "Тварь я дрожащая или право имею?  key{}"
echo "Тварь я дрожащая или право имею?" > /home/student/.t.txt
```
