-- TEMPORARY. Replace with nl2sql/schema.py (Drew), which will read the
-- schema from the database instead of this fixed copy.
--
-- Pagila schema as the model sees it in the prompt: base tables in public,
-- their columns, types, keys, and the mpaa_rating values. Generated once
-- on 2026-10-04 from our Tiger database as nl2sql_reader. Monthly payment
-- partitions are left out; queries use the parent payment table.
-- staff.password and staff.picture are left out on purpose so the model
-- is not offered them. That is not access control: the read-only role
-- can still read them, and column checks are not built yet.
--
-- Not a setup script: the database is built with db/02_load_pagila.sh.

CREATE TYPE mpaa_rating AS ENUM ('G', 'PG', 'PG-13', 'R', 'NC-17');

CREATE TABLE actor (
  actor_id integer NOT NULL,
  first_name text NOT NULL,
  last_name text NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (actor_id)
);

CREATE TABLE address (
  address_id integer NOT NULL,
  address text NOT NULL,
  address2 text,
  district text NOT NULL,
  city_id integer NOT NULL,
  postal_code text,
  phone text NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (address_id),
  FOREIGN KEY (city_id) REFERENCES city(city_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE category (
  category_id integer NOT NULL,
  name text NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (category_id)
);

CREATE TABLE city (
  city_id integer NOT NULL,
  city text NOT NULL,
  country_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (city_id),
  FOREIGN KEY (country_id) REFERENCES country(country_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE country (
  country_id integer NOT NULL,
  country text NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (country_id)
);

CREATE TABLE customer (
  customer_id integer NOT NULL,
  store_id integer NOT NULL,
  first_name text NOT NULL,
  last_name text NOT NULL,
  email text,
  address_id integer NOT NULL,
  activebool boolean NOT NULL,
  create_date date NOT NULL,
  last_update timestamp with time zone,
  active integer,
  PRIMARY KEY (customer_id),
  FOREIGN KEY (address_id) REFERENCES address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (store_id) REFERENCES store(store_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE film (
  film_id integer NOT NULL,
  title text NOT NULL,
  description text,
  release_year year,
  language_id integer NOT NULL,
  original_language_id integer,
  rental_duration smallint NOT NULL,
  rental_rate numeric(4,2) NOT NULL,
  length smallint,
  replacement_cost numeric(5,2) NOT NULL,
  rating mpaa_rating,
  last_update timestamp with time zone NOT NULL,
  special_features text[],
  fulltext tsvector NOT NULL,
  PRIMARY KEY (film_id),
  FOREIGN KEY (language_id) REFERENCES language(language_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (original_language_id) REFERENCES language(language_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE film_actor (
  actor_id integer NOT NULL,
  film_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (actor_id, film_id),
  FOREIGN KEY (actor_id) REFERENCES actor(actor_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (film_id) REFERENCES film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE film_category (
  film_id integer NOT NULL,
  category_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (film_id, category_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (film_id) REFERENCES film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE inventory (
  inventory_id integer NOT NULL,
  film_id integer NOT NULL,
  store_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (inventory_id),
  FOREIGN KEY (film_id) REFERENCES film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (store_id) REFERENCES store(store_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE language (
  language_id integer NOT NULL,
  name character(20) NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (language_id)
);

CREATE TABLE payment (
  payment_id integer NOT NULL,
  customer_id integer NOT NULL,
  staff_id integer NOT NULL,
  rental_id integer NOT NULL,
  amount numeric(5,2) NOT NULL,
  payment_date timestamp with time zone NOT NULL,
  PRIMARY KEY (payment_date, payment_id)
);

CREATE TABLE rental (
  rental_id integer NOT NULL,
  rental_date timestamp with time zone NOT NULL,
  inventory_id integer NOT NULL,
  customer_id integer NOT NULL,
  return_date timestamp with time zone,
  staff_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (rental_id),
  FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (staff_id) REFERENCES staff(staff_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE staff (
  staff_id integer NOT NULL,
  first_name text NOT NULL,
  last_name text NOT NULL,
  address_id integer NOT NULL,
  email text,
  store_id integer NOT NULL,
  active boolean NOT NULL,
  username text NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (staff_id),
  FOREIGN KEY (address_id) REFERENCES address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (store_id) REFERENCES store(store_id)
);

CREATE TABLE store (
  store_id integer NOT NULL,
  manager_staff_id integer NOT NULL,
  address_id integer NOT NULL,
  last_update timestamp with time zone NOT NULL,
  PRIMARY KEY (store_id),
  FOREIGN KEY (address_id) REFERENCES address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT
);
