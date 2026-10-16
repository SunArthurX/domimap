package com.example.trade;

import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.apache.dubbo.config.annotation.DubboService;

@DubboService
public class OrderPriceService {

    private RocketMQTemplate rocketMQTemplate;

    public boolean changePrice(Long orderId, java.math.BigDecimal price) {
        orderMapper.updatePrice(orderId, price);
        rocketMQTemplate.syncSend("trade-price-changed", "order:" + orderId);
        return true;
    }
}
