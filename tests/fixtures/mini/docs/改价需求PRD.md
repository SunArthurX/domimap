# 订单改价需求（PRD）

## 背景
订单域支持对 t_order 单价调整，需要防并发覆盖。

## 方案
- OrderController 暴露 POST /trade/price
- 使用 price_version 乐观锁
- 改价成功后发送 RocketMQ 消息 trade-price-changed，商品域 PriceSyncListener 消费同步

## 涉及表
t_order（写）、t_item（商品域，价格展示）
