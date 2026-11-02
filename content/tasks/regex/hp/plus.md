# Сколько угодно: * и +

`{ }` хорош, когда знаешь, сколько повторов. А если не знаешь:

    *      сколько угодно раз — и ноль тоже
    +      хотя бы один раз (это -E)

    ni*ght       nght, night, niiiiight
    ni+ght       night, niiiiight — но не nght
    [0-9]+       число из любого количества цифр

    $ echo "arabian niiiiiight arabian night arabian nght" | grep 'ni*ght'
    arabian ==niiiiiight== arabian ==night== arabian ==nght==
    $ echo "arabian niiiiiight arabian night arabian nght" | grep -E 'ni+ght'
    arabian ==niiiiiight== arabian ==night== arabian nght

Звёздочка и плюс относятся к символу (или набору) прямо перед ними.
