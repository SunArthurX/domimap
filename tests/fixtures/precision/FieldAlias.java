package com.example.prec;
public class FieldAlias {
    private Overload overload;
    public void run() {
        overload.changePrice("alias");
        this.overload.changePrice(1L, null);
    }
}
