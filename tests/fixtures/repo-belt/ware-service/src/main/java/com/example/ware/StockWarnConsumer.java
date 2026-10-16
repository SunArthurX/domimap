package com.example.ware;

import org.apache.kafka.clients.consumer.KafkaListener;
import org.apache.dubbo.config.annotation.DubboReference;

@Component
public class StockWarnConsumer {

    @DubboReference
    private com.example.trade.OrderPriceService orderPriceService;

    @KafkaListener(topics = {"stock-warn", "stock-warn-dlq"})
    public void onStockWarn(String msg) {
        // 库存预警联动改价
    }
}
