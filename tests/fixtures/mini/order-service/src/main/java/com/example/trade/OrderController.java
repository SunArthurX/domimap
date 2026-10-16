package com.example.trade;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/trade")
public class OrderController {

    @PostMapping("/price")
    public Boolean changePrice(@RequestBody PriceReq req) {
        return orderPriceService.changePrice(req.getOrderId(), req.getPrice());
    }

    @GetMapping("/detail")
    public Order detail(Long id) {
        return orderService.getById(id);
    }
}
