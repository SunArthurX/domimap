// 订单列表页：提交改价
export async function submitPriceChange(orderId: number, price: number) {
  const resp = await fetch('/trade/price', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ orderId, price })
  });
  return resp.json();
}
