#include <linux/module.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Студент");
MODULE_DESCRIPTION("Первый модуль");

static int __init hello_init(void)
{
	pr_info("hello: привет из ядра\n");
	return 0;
}

static void __exit hello_exit(void)
{
	pr_info("hello: пока\n");
}

module_init(hello_init);
module_exit(hello_exit);
