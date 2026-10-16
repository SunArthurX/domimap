package com.example.prec;
import java.util.concurrent.Callable;
public class EmptyAndNested {
    public void doNothing() { }
    public Runnable outer() {
        Runnable r = () -> { helperCall(); };
        Callable<String> c = new Callable<String>() {
            public String call() { return helperCall(); }
        };
        return r;
    }
    public String helperCall() { return "ok"; }
}
