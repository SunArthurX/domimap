package com.example.trade;

public interface OrderMapper {
    int updatePrice(Long orderId, java.math.BigDecimal price);
    Order selectById(Long orderId);
}
