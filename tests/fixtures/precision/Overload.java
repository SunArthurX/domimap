package com.example.prec;
public class Overload {
    public boolean changePrice(Long orderId, java.math.BigDecimal price) { return true; }
    public boolean changePrice(String note) { return false; }
    public void caller() {
        changePrice(1L, java.math.BigDecimal.TEN);
        changePrice("x");
    }
}
