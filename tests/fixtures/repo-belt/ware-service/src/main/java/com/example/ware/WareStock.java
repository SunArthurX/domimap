package com.example.ware;

import javax.persistence.*;

@Entity
@Table(name = "t_ware_stock")
public class WareStock {

    @Column(name = "sku_code")
    private String skuCode;

    @Column(name = "warn_threshold")
    private Integer warnThreshold;
}
