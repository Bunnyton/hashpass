// hello — драйвер /dev/hashpass: что записали, то и читается
#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>

MODULE_LICENSE("GPL");

static char msg[256] = "Hello, kernel!\n";
static size_t len = 15;

static ssize_t hp_read(struct file *f, char __user *buf, size_t n, loff_t *off)
{
	return simple_read_from_buffer(buf, n, off, msg, len);
}

static ssize_t hp_write(struct file *f, const char __user *buf, size_t n, loff_t *off)
{
	if (n > sizeof(msg))
		n = sizeof(msg);
	if (copy_from_user(msg, buf, n))
		return -EFAULT;
	len = n;
	return n;
}

static const struct file_operations hp_fops = {
	.owner = THIS_MODULE,
	.read  = hp_read,
	.write = hp_write,
};

static struct miscdevice hp_dev = {
	.minor = MISC_DYNAMIC_MINOR,
	.name  = "hashpass",
	.fops  = &hp_fops,
	.mode  = 0666,
};

module_misc_device(hp_dev);
