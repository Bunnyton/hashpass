#include <linux/module.h>
#include <linux/init.h>
#include <linux/slab.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Олег");
MODULE_DESCRIPTION("Варит пельмени в ядре");

struct pelmen {
	const char *filling;
	int minutes;
};

static const char *fillings[] = { "говядина", "свинина", "курица", "грибы", "картошка" };
static struct pelmen *pot[ARRAY_SIZE(fillings)];	/* кастрюля: по месту на начинку */

static noinline void cook(struct pelmen *p)
{
	pr_info("pelmen: %s — %d мин\n", p->filling, p->minutes);
}

static int __init pelmen_init(void)
{
	int i;

	for (i = 0; i < 4; i++) {
		pot[i] = kmalloc(sizeof(*pot[i]), GFP_KERNEL);
		if (!pot[i])
			return -ENOMEM;
		pot[i]->filling = fillings[i];
		pot[i]->minutes = 7;
	}
	for (i = 0; i < ARRAY_SIZE(pot); i++)
		cook(pot[i]);
	pr_info("pelmen: сварено %d\n", i);
	return 0;
}

static void __exit pelmen_exit(void)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(pot); i++)
		kfree(pot[i]);
	pr_info("pelmen: кастрюля вымыта\n");
}

module_init(pelmen_init);
module_exit(pelmen_exit);
