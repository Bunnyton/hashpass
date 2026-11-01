#!/usr/bin/env python3
"""Отчёт по заказам за день: сколько заказов, сколько из них со скидкой."""
import sys

cnt = 0
cnt_max = 1000
discount_cnt = 0
account = "shop-01"


def read_orders(path):
    with open(path) as f:
        return [line.split(";") for line in f if line.strip()]


def main(path):
    global cnt, discount_cnt
    for order in read_orders(path):
        cnt += 1
        if order[3] == "discount":
            discount_cnt += 1
        if cnt > cnt_max:
            print("слишком много заказов, считаю первые", cnt_max)
            break
    print(account, "заказов:", cnt)
    print(account, "со скидкой:", discount_cnt)
    share = discount_cnt / cnt if cnt else 0
    print("доля со скидкой:", round(share * 100), "%")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "orders.csv")
