package com.example.item;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/item")
public class ItemController {

    @GetMapping("/list")
    public java.util.List<Item> list(Long shopId) {
        return itemService.listByShop(shopId);
    }
}
