// отправляет заказ на сервер заказов
const API = "/api/orders";
function order(dish, count) {
  return fetch(API, { method: "POST", body: JSON.stringify({ dish, count }) });
}
