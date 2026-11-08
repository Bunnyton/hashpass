#include <linux/module.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Студент");
MODULE_DESCRIPTION("Первый модуль");

static char *who = "мир";
module_param(who, charp, 0644);
MODULE_PARM_DESC(who, "Кого приветствовать");

static int __init hello_init(void)
{
	pr_info("hello: Привет, %s!\n", who);
	return 0;
}

static void __exit hello_exit(void)
{
	pr_info("hello: Пока, %s!\n", who);
}

module_init(hello_init);
module_exit(hello_exit);
