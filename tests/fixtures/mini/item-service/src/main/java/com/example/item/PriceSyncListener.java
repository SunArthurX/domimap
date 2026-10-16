package com.example.item;

import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.apache.dubbo.config.annotation.DubboReference;

@Component
@RocketMQMessageListener(topic = "trade-price-changed", consumerGroup = "item-sync")
public class PriceSyncListener implements RocketMQListener<String> {

    @DubboReference
    private com.example.trade.OrderPriceService orderPriceService;

    public void onMessage(String msg) {
        // 商品侧价格同步
    }
}
