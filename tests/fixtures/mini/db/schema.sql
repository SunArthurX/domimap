CREATE TABLE t_order (
  id bigint NOT NULL,
  price decimal(18,4),
  price_version int,
  status tinyint,
  PRIMARY KEY (id)
);
CREATE TABLE t_item (
  id bigint NOT NULL,
  sku varchar(64),
  price decimal(18,4),
  PRIMARY KEY (id)
);
